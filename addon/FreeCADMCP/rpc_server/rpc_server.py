"""FreeCAD transport and GUI dispatch; modeling is performed by Python cells."""

import base64
import json
import os
import tempfile
import threading
import uuid
from xmlrpc.client import Fault

import FreeCAD
import FreeCADGui
from PySide import QtCore

from rpc_server.commands import register_commands, schedule_toggle_sync
from rpc_server.document_inspection import inspect_document as inspect_document_data
from rpc_server.document_operations import perform_document_operation
from rpc_server.gui_dispatch import (
    cleanup_waker, dispatch_to_gui, get_dispatch_status, init_waker,
    process_gui_tasks, request_shutdown,
)
from rpc_server.ip_filter import FilteredXMLRPCServer
from rpc_server.python_session import PythonSession, MAX_CODE_CHARS
from rpc_server.python_testing import PythonTestRunner, find_freecadcmd
from rpc_server.resource_operations import resource_operations as perform_resource_operation
from rpc_server.settings import load_settings
from rpc_server.unit_safety import preferred_units
from rpc_server.view_manager import save_view

rpc_server_thread = None
rpc_server_instance = None
_stop_thread = None

_python_session = PythonSession({
    "FreeCAD": FreeCAD, "App": FreeCAD,
    "FreeCADGui": FreeCADGui, "Gui": FreeCADGui,
})


class FreeCADRPC:
    def __init__(self):
        self._test_runner = PythonTestRunner(
            find_freecadcmd(FreeCAD.getHomePath()), FreeCAD.Version(),
        )

    def ping(self):
        return True

    def get_runtime_status(self) -> dict:
        """Report status without queueing anything on the GUI thread."""
        status = {
            "success": True,
            "rpc_server": "running",
            "gui_dispatch": get_dispatch_status(),
            "freecad_version": list(FreeCAD.Version()),
            **_python_session.status(),
            "test_worker": self._test_runner.status(),
        }
        try:
            status["units"] = preferred_units(FreeCAD)
        except Exception:
            pass
        return status

    def test_python(self, code, document_path=None, timeout_seconds=60) -> str:
        # Run on this RPC request thread: no live GUI or document access.
        return json.dumps(
            self._test_runner.run(
                code, document_path, timeout_seconds, preferred_units(FreeCAD),
            ),
            ensure_ascii=False, allow_nan=False,
        )

    def execute_python(self, code: str, timeout_seconds: int = 90) -> str:
        """Run a Python cell and encode its result as JSON across XML-RPC."""
        if not isinstance(code, str) or len(code) > MAX_CODE_CHARS:
            raise ValueError(f"code must be a string of at most {MAX_CODE_CHARS} characters")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be an integer between 1 and 3600")
        cell_id = uuid.uuid4().hex
        response = dispatch_to_gui(
            lambda: _python_session.run(code, cell_id),
            timeout=timeout_seconds,
            operation_name=f"execute_python:{cell_id}",
        )
        if not isinstance(response, dict):
            response = {"success": False, "error": str(response)}
        response.setdefault("cell_id", cell_id)
        response.setdefault("session_id", _python_session.session_id)
        return json.dumps(response, ensure_ascii=False, allow_nan=False)

    def document_operations(
        self, action, document=None, path=None,
        discard_changes=False, overwrite=False,
    ) -> str:
        """Manage live FreeCAD documents on the GUI thread."""
        if not isinstance(action, str):
            raise ValueError("action must be a string")
        if document is not None and not isinstance(document, str):
            raise ValueError("document must be a string or null")
        if path is not None and not isinstance(path, str):
            raise ValueError("path must be a string or null")
        if type(discard_changes) is not bool or type(overwrite) is not bool:
            raise ValueError("discard_changes and overwrite must be booleans")

        def perform():
            try:
                return perform_document_operation(
                    FreeCAD, FreeCADGui, action, document, path,
                    discard_changes, overwrite,
                )
            except Exception as exc:
                return {
                    "success": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }

        result = dispatch_to_gui(
            perform, operation_name=f"document_operations:{action}",
        )
        response = (
            result if isinstance(result, dict) and result.get("success") is False
            else {"success": True, "result": result}
        )
        return json.dumps(response, ensure_ascii=False, allow_nan=False)

    def inspect_document(
        self, document=None, object_name=None, properties=None, max_depth=6,
    ) -> str:
        """Inspect native FreeCAD structure on the GUI thread."""
        if document is not None and not isinstance(document, str):
            raise ValueError("document must be a string or null")
        if isinstance(document, str) and len(document) > 255:
            raise ValueError("document must be at most 255 characters")
        if object_name is not None and not isinstance(object_name, str):
            raise ValueError("object_name must be a string or null")
        if isinstance(object_name, str) and len(object_name) > 255:
            raise ValueError("object_name must be at most 255 characters")
        if properties is not None and (
            not isinstance(properties, list)
            or len(properties) > 100
            or any(not isinstance(name, str) or len(name) > 255 for name in properties)
        ):
            raise ValueError(
                "properties must be at most 100 strings of at most 255 characters"
            )
        if type(max_depth) is not int or not 1 <= max_depth <= 10:
            raise ValueError("max_depth must be an integer between 1 and 10")

        def perform():
            try:
                return inspect_document_data(
                    FreeCAD, FreeCADGui, document, object_name, properties, max_depth,
                )
            except Exception as exc:
                return {
                    "success": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }

        result = dispatch_to_gui(perform, operation_name="inspect_document")
        response = (
            result if isinstance(result, dict) and result.get("success") is False
            else {"success": True, "result": result}
        )
        return json.dumps(response, ensure_ascii=False, allow_nan=False)

    def resource_operations(
        self, action, query=None, provider=None, resource_id=None, document=None,
        properties=None, attach_to=None, limit=10,
    ) -> str:
        """Search and insert resources through installed providers."""
        values = {
            "action": action, "query": query, "provider": provider,
            "resource_id": resource_id, "document": document, "attach_to": attach_to,
        }
        if any(value is not None and not isinstance(value, str) for value in values.values()):
            raise ValueError("resource string arguments must be strings or null")
        if not isinstance(action, str) or action not in {"providers", "search", "inspect", "insert"}:
            raise ValueError("unsupported resource action")
        if any(isinstance(value, str) and len(value) > 1000 for value in values.values()):
            raise ValueError("resource string arguments must be at most 1000 characters")
        if properties is not None and (
            not isinstance(properties, dict) or len(properties) > 50
            or any(not isinstance(key, str) or len(key) > 100 for key in properties)
            or any(not isinstance(value, (str, int, float, bool)) for value in properties.values())
        ):
            raise ValueError("properties must contain at most 50 scalar values")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be an integer between 1 and 50")

        def perform():
            try:
                return perform_resource_operation(
                    FreeCAD, FreeCADGui, action, query, provider, resource_id,
                    document, properties, attach_to, limit,
                )
            except Exception as exc:
                return {
                    "success": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }

        result = dispatch_to_gui(
            perform, operation_name=f"resource_operations:{action}",
        )
        response = (
            result if isinstance(result, dict) and result.get("success") is False
            else {"success": True, "result": result}
        )
        return json.dumps(response, ensure_ascii=False, allow_nan=False)


    def get_view(self, width=1024, height=768) -> str:
        if any(type(size) is not int or not 1 <= size <= 4096 for size in (width, height)):
            raise ValueError("Image dimensions must be integers between 1 and 4096")

        def capture():
            # Create and delete the file on the GUI thread, even if RPC times out.
            with tempfile.TemporaryDirectory(prefix="freecad_mcp_view_") as directory:
                path = os.path.join(directory, "view.png")
                save_view(path, width, height)
                with open(path, "rb") as image_file:
                    return (base64.b64encode(image_file.read()).decode("ascii"),)

        result = dispatch_to_gui(capture, operation_name="get_view")
        # Dispatch errors are strings too; wrap success to disambiguate them.
        if not isinstance(result, tuple):
            raise Fault(1, json.dumps(result))
        return result[0]

def start_rpc_server(port=9875):
    global rpc_server_thread, rpc_server_instance

    if rpc_server_instance:
        return "RPC Server already running."

    # A previous stop may still be draining an in-flight request off-thread;
    # binding before its server_close() would hit the old socket.
    if _stop_thread is not None and _stop_thread.is_alive():
        _stop_thread.join(timeout=5.0)
        if _stop_thread.is_alive():
            return ("RPC Server is still stopping (a request is draining); "
                    "try again in a few seconds.")

    settings = load_settings()
    remote_enabled = settings.get("remote_enabled", False)
    allowed_ips = settings.get("allowed_ips", "127.0.0.1")

    if remote_enabled:
        host = "0.0.0.0"
    else:
        host = "127.0.0.1"

    rpc_server_instance = FilteredXMLRPCServer(
        (host, port), allowed_ips_str=allowed_ips, allow_none=True, logRequests=False
    )
    rpc_server_instance.register_instance(FreeCADRPC())

    def server_loop():
        FreeCAD.Console.PrintMessage(f"RPC Server started at {host}:{port}\n")
        if remote_enabled:
            FreeCAD.Console.PrintMessage(f"Remote connections enabled. Allowed IPs: {allowed_ips}\n")
        rpc_server_instance.serve_forever()

    rpc_server_thread = threading.Thread(target=server_loop, daemon=True)
    rpc_server_thread.start()

    init_waker()
    QtCore.QTimer.singleShot(500, process_gui_tasks)

    msg = f"RPC Server started at {host}:{port}."
    if remote_enabled:
        msg += f" Allowed IPs: {allowed_ips}"
    return msg


def stop_rpc_server():
    global rpc_server_instance, rpc_server_thread, _stop_thread

    if not rpc_server_instance:
        return "RPC Server was not running."

    server = rpc_server_instance
    thread = rpc_server_thread
    rpc_server_instance = None
    rpc_server_thread = None

    request_shutdown()
    cleanup_waker()

    def _shutdown_and_close():
        # shutdown() only stops the accept loop; in-flight requests run in
        # their own daemon threads and are not waited for. Kept off the GUI
        # thread so a menu command cannot block the UI. server_close() must
        # always follow, or the listening socket stays bound and Stop -> Start
        # fails with EADDRINUSE.
        try:
            server.shutdown()
            if thread is not None:
                thread.join(timeout=10.0)
                if thread.is_alive():
                    FreeCAD.Console.PrintWarning(
                        "MCP RPC: server thread still draining a request; "
                        "socket closes when it finishes.\n"
                    )
        finally:
            server.server_close()
        FreeCAD.Console.PrintMessage("RPC Server stopped.\n")

    _stop_thread = threading.Thread(target=_shutdown_and_close, daemon=True)
    _stop_thread.start()
    return "RPC Server stopping…"


register_commands()
schedule_toggle_sync()
