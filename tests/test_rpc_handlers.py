from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
from xmlrpc.client import Fault

import pytest

from test_gui_dispatch import load_gui_dispatch, ThreadedWaker
from test_rpc_concurrency import client, running_server


RPC_PATH = Path(__file__).resolve().parents[1] / "addon/FreeCADMCP/rpc_server/rpc_server.py"


@pytest.fixture
def rpc_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[types.ModuleType]:
    """Exercise real RPC and dispatch; stub only GUI/FreeCAD dependencies."""
    with load_gui_dispatch() as dispatch:
        freecad = dispatch.FreeCAD
        freecad.Version = lambda: ["1", "1", "3"]
        freecad.getHomePath = lambda: "/missing-freecad-test-installation"
        freecad.Console.PrintMessage = lambda _message: None
        freecad.Console.PrintWarning = lambda _message: None
        stubs = {
            "gui_dispatch": dispatch,
            "commands": types.SimpleNamespace(
                register_commands=lambda: None, schedule_toggle_sync=lambda: None,
            ),
            "settings": types.SimpleNamespace(load_settings=lambda: {}),
            "view_manager": types.SimpleNamespace(save_view=lambda *_args: None),
        }
        with monkeypatch.context() as patch:
            for name, stub in stubs.items():
                patch.setitem(sys.modules, f"rpc_server.{name}", stub)
            spec = importlib.util.spec_from_file_location("_rpc_handler_test", RPC_PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            waker = ThreadedWaker(dispatch)
            dispatch._waker = waker
            module.test_dispatch = dispatch
            try:
                yield module
            finally:
                waker.join()


def test_python_cells_run_through_real_dispatch_and_xmlrpc(rpc_module):
    rpc = rpc_module.FreeCADRPC()
    with running_server(rpc) as (host, port), client(host, port, 5) as proxy:
        assert json.loads(proxy.execute_python("answer = 2**80"))["success"]
        result = json.loads(proxy.execute_python("{'answer': answer}"))
        assert result["result"] == {"answer": 2**80}
        failed = json.loads(proxy.execute_python("assert answer == 0"))
        assert failed["error"]["type"] == "AssertionError"
        assert "assert answer == 0" in failed["error"]["traceback"]


def test_document_operations_run_through_dispatch_and_xmlrpc(rpc_module):
    document = types.SimpleNamespace(
        Name="Doc", Label="Document", FileName="", Modified=False, Objects=[],
    )
    documents = {"Doc": document}
    rpc_module.FreeCAD.listDocuments = lambda: documents
    rpc_module.FreeCAD.activeDocument = lambda: document
    rpc_module.FreeCAD.getDocument = lambda name: documents[name]
    rpc_module.FreeCAD.setActiveDocument = lambda _name: None
    rpc_module.FreeCADGui.getDocument = lambda name: documents[name]

    with running_server(rpc_module.FreeCADRPC()) as (host, port), client(host, port, 5) as proxy:
        result = json.loads(proxy.document_operations("list", None, None, False, False))

    assert result == {"success": True, "result": {"documents": [{
        "name": "Doc", "label": "Document", "path": None,
        "active": True, "modified": False, "object_count": 0,
    }]}}


def test_document_operation_errors_are_structured(rpc_module):
    rpc_module.FreeCAD.activeDocument = lambda: None
    result = json.loads(rpc_module.FreeCADRPC().document_operations("save"))
    assert result == {
        "success": False,
        "error": {"type": "DocumentOperationError", "message": "No active document"},
    }


def test_document_inspection_runs_through_dispatch_and_xmlrpc(rpc_module):
    document = types.SimpleNamespace(
        Name="Doc", Label="Document", FileName="", Objects=[],
    )
    rpc_module.FreeCAD.activeDocument = lambda: document
    rpc_module.FreeCADGui.getDocument = lambda _name: types.SimpleNamespace(Modified=False)

    with running_server(rpc_module.FreeCADRPC()) as (host, port), client(host, port, 5) as proxy:
        result = json.loads(proxy.inspect_document(None, None, None, 6))

    assert result == {"success": True, "result": {
        "document": {
            "name": "Doc", "label": "Document", "path": None,
            "active": True, "modified": False, "object_count": 0,
        },
        "tree": [],
    }}


def test_resource_operations_run_through_dispatch_and_xmlrpc(rpc_module):
    rpc_module.perform_resource_operation = lambda *args: {
        "providers": [{"id": "fasteners"}], "received": list(args[2:]),
    }
    with running_server(rpc_module.FreeCADRPC()) as (host, port), client(host, port, 5) as proxy:
        result = json.loads(proxy.resource_operations(
            "search", "socket screw", "fasteners", None, None, None, None, 5,
        ))
    assert result == {"success": True, "result": {
        "providers": [{"id": "fasteners"}],
        "received": ["search", "socket screw", "fasteners", None, None, None, None, 5],
    }}


@pytest.mark.parametrize("limit", [0, 51, True, "5"])
def test_invalid_resource_limit_is_rejected(rpc_module, limit):
    with pytest.raises(ValueError, match="limit"):
        rpc_module.FreeCADRPC().resource_operations("providers", limit=limit)


def test_python_status_responds_while_cell_runs(rpc_module):
    rpc = rpc_module.FreeCADRPC()
    rpc_module.FreeCAD.Version = lambda: ["1", "1", "3"]
    entered, release = threading.Event(), threading.Event()
    rpc_module.FreeCAD.test_entered = entered
    rpc_module.FreeCAD.test_release = release
    with running_server(rpc) as (host, port), ThreadPoolExecutor(max_workers=2) as workers:
        def request(method, *args):
            with client(host, port, 5) as proxy:
                return getattr(proxy, method)(*args)
        execution = workers.submit(
            request, "execute_python",
            "App.test_entered.set()\nApp.test_release.wait(5)", 1,
        )
        try:
            assert entered.wait(2)
            status = request("get_runtime_status")
            assert status["current_cell"]["cell_id"]
            assert status["gui_dispatch"]["state"] == "busy"
            assert json.loads(execution.result(timeout=2))["code"] == "GUI_DISPATCH_STUCK"
            assert request("get_runtime_status")["gui_dispatch"]["state"] == "stuck"
        finally:
            release.set()



def test_cell_assignments_cannot_shadow_bridge_functions(rpc_module):
    rpc = rpc_module.FreeCADRPC()
    original = rpc_module.dispatch_to_gui
    result = json.loads(rpc.execute_python("dispatch_to_gui = None\nApp = None"))
    assert result["success"]
    assert rpc_module.dispatch_to_gui is original
    assert json.loads(rpc.execute_python("App.Version()"))["result"] == ["1", "1", "3"]


def test_capture_failure_is_a_fault_not_an_image(rpc_module):
    def fail(*args):
        raise RuntimeError("No active document")
    rpc_module.save_view = fail
    with pytest.raises(Fault, match="No active document"):
        rpc_module.FreeCADRPC().get_view()


@pytest.mark.parametrize("timeout", [0, -1, 3601, True, "3"])
def test_invalid_execution_timeout_rejected(rpc_module, timeout):
    with pytest.raises(ValueError):
        rpc_module.FreeCADRPC().execute_python("1", timeout)
