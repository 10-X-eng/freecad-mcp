import asyncio
import json
import threading

import pytest

from freecad_mcp import server


def test_only_transport_and_execution_tools_are_registered():
    async def inspect():
        tools = await server.mcp.list_tools()
        assert [tool.name for tool in tools] == [
            "execute_python", "get_view", "get_runtime_status",
        ]
        assert await server.mcp.list_prompts() == []
        schema = tools[0].inputSchema
        assert schema["required"] == ["code"]
        assert schema["properties"]["timeout_seconds"]["maximum"] == 3600
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
            assert json.loads(result.content[0].text)["gui_dispatch"]["state"] == "busy"
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


def test_unavailable_bridge_reports_connection_failure(monkeypatch):
    class Connection:
        def get_runtime_status(self):
            raise ConnectionRefusedError("FreeCAD is not running")
    monkeypatch.setattr(server.state, "freecad_connection", Connection())
    result = asyncio.run(server.get_runtime_status())
    assert result.isError
    assert "ConnectionRefusedError" in result.content[0].text
