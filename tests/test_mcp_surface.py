import asyncio
import json
import threading

from freecad_mcp import server


def test_focused_python_and_document_tools_are_registered():
    async def inspect():
        tools = await server.mcp.list_tools()
        assert [tool.name for tool in tools] == [
            "document_operations", "execute_python", "inspect_document", "get_view",
            "get_runtime_status", "test_python",
        ]
        assert await server.mcp.list_prompts() == []
        document_schema = tools[0].inputSchema
        assert document_schema["required"] == ["action"]
        assert document_schema["properties"]["action"]["enum"] == [
            "list", "new", "open", "activate", "save", "save_as", "reload", "close",
        ]
        execution_schema = tools[1].inputSchema
        assert execution_schema["required"] == ["code"]
        assert execution_schema["properties"]["timeout_seconds"]["maximum"] == 3600
        inspection_schema = tools[2].inputSchema
        assert inspection_schema["properties"]["max_depth"]["maximum"] == 10
        assert sum(len(tool.description.split()) for tool in tools) <= 250
        assert server.mcp.instructions is None
    asyncio.run(inspect())


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
    result = asyncio.run(server.mcp.call_tool("execute_python", {"code": "assert False"}))
    assert result.isError
    assert "AssertionError at line 2" in result.content[0].text


def test_document_operation_returns_structured_result(monkeypatch):
    class Connection:
        def document_operations(self, *args):
            assert args == ("list", None, None, False, False)
            return {"success": True, "result": {"documents": []}}
    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.mcp.call_tool("document_operations", {"action": "list"}))
    assert not result.isError
    assert json.loads(result.content[0].text) == {"result": {"documents": []}}


def test_document_inspection_returns_structured_result(monkeypatch):
    class Connection:
        def inspect_document(self, *args):
            assert args == (None, None, None, 6)
            return {"success": True, "result": {"document": {"name": "Model"}}}
    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.mcp.call_tool("inspect_document", {}))
    assert not result.isError
    assert json.loads(result.content[0].text) == {
        "result": {"document": {"name": "Model"}},
    }


def test_unavailable_bridge_reports_connection_failure(monkeypatch):
    class Connection:
        def get_runtime_status(self):
            raise ConnectionRefusedError("FreeCAD is not running")
    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.get_runtime_status())
    assert result.isError
    assert "ConnectionRefusedError" in result.content[0].text
