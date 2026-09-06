import asyncio
import json
import re
import threading

from freecad_mcp import server


def test_focused_python_and_document_tools_are_registered():
    async def inspect():
        tools = await server.mcp.list_tools()
        assert [tool.name for tool in tools] == [
            "GetHelp", "DocumentOperations", "ExecutePython", "InspectDocument",
            "ResourceOperations", "GetView", "GetRuntimeStatus", "TestPython",
        ]
        assert all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", tool.name) for tool in tools)
        assert await server.mcp.list_prompts() == []
        help_schema = tools[0].inputSchema
        assert help_schema["properties"]["topic"]["enum"] == [
            "start", "python", "documents", "workbenches", "resources",
            "inspection", "validation", "bim", "fem", "cam", "blocked",
        ]
        document_schema = tools[1].inputSchema
        assert document_schema["required"] == ["action"]
        assert document_schema["properties"]["action"]["enum"] == [
            "list", "new", "open", "activate", "save", "save_as", "reload", "close",
        ]
        execution_schema = tools[2].inputSchema
        assert execution_schema["required"] == ["code"]
        assert execution_schema["properties"]["timeout_seconds"]["maximum"] == 3600
        inspection_schema = tools[3].inputSchema
        assert inspection_schema["properties"]["max_depth"]["maximum"] == 10
        resource_schema = tools[4].inputSchema
        assert resource_schema["properties"]["action"]["enum"] == [
            "providers", "search", "inspect", "insert",
        ]
        assert resource_schema["properties"]["limit"]["maximum"] == 50
        assert sum(len(tool.description.split()) for tool in tools) <= 300
        assert "GetHelp(topic='start')" in server.mcp.instructions
        assert "never invent or rewrite" in server.mcp.instructions
    asyncio.run(inspect())


def test_help_is_focused_and_does_not_require_freecad_connection(monkeypatch):
    monkeypatch.setattr(server.state, "freecad_connection", None)
    monkeypatch.setattr(server, "connection", lambda: (_ for _ in ()).throw(
        ConnectionRefusedError("offline")
    ))
    result = asyncio.run(server.mcp.call_tool("GetHelp", {"topic": "cam"}))
    data = json.loads(result.content[0].text)
    assert data["topic"] == "cam"
    assert "CAMWorkbench" in " ".join(data["guidance"])
    assert "PathWorkbench" in " ".join(data["guidance"])
    assert len(result.content[0].text.split()) < 180


def test_help_includes_live_freecad_units(monkeypatch):
    class Connection:
        def get_runtime_status(self):
            return {
                "success": True,
                "units": {"schema": "Imperial", "preferred": {"length": "in"}},
            }

    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.mcp.call_tool("GetHelp", {"topic": "resources"}))
    data = json.loads(result.content[0].text)
    assert data["freecad_units"] == {
        "schema": "Imperial", "preferred": {"length": "in"},
    }


def test_status_remains_responsive_through_same_mcp_server(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class Connection:
        def execute_python(self, *_args):
            entered.set()
            release.wait(3)
            return {"success": True, "result": 42}

        def get_runtime_status(self):
            return {"success": True, "gui_dispatch": {"state": "busy"}}

    monkeypatch.setattr(server.state, "freecad_connection", Connection())

    async def exercise():
        execution = asyncio.create_task(server.execute_python("42"))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            result = await asyncio.wait_for(server.get_runtime_status(), 1)
            assert json.loads(result.content[0].text)["gui"]["state"] == "busy"
        finally:
            release.set()
            await execution
    asyncio.run(exercise())


def test_python_failure_is_mcp_error_with_traceback(monkeypatch):
    class Connection:
        def execute_python(self, *_args):
            return {"success": False, "error": {"traceback": "AssertionError at line 2"}}
    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.mcp.call_tool("ExecutePython", {"code": "assert False"}))
    assert result.isError
    assert "AssertionError at line 2" in result.content[0].text


def test_document_operation_returns_structured_result(monkeypatch):
    class Connection:
        def document_operations(self, *args):
            assert args == ("list", None, None, False, False)
            return {"success": True, "result": {"documents": []}}
    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.mcp.call_tool("DocumentOperations", {"action": "list"}))
    assert not result.isError
    assert json.loads(result.content[0].text) == {"result": {"documents": []}}


def test_document_inspection_returns_structured_result(monkeypatch):
    class Connection:
        def inspect_document(self, *args):
            assert args == (None, None, None, 6)
            return {"success": True, "result": {"document": {"name": "Model"}}}
    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.mcp.call_tool("InspectDocument", {}))
    assert not result.isError
    assert json.loads(result.content[0].text) == {
        "result": {"document": {"name": "Model"}},
    }


def test_resource_operation_returns_structured_result(monkeypatch):
    class Connection:
        def resource_operations(self, *args):
            assert args == ("providers", None, None, None, None, None, None, 10)
            return {"success": True, "result": {"providers": []}}
    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.mcp.call_tool("ResourceOperations", {"action": "providers"}))
    assert not result.isError
    assert json.loads(result.content[0].text) == {"result": {"providers": []}}


def test_unavailable_bridge_reports_connection_failure(monkeypatch):
    class Connection:
        def get_runtime_status(self):
            raise ConnectionRefusedError("FreeCAD is not running")
    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.get_runtime_status())
    assert result.isError
    assert "ConnectionRefusedError" in result.content[0].text
