import asyncio

from freecad_mcp.server import mcp
from freecad_mcp.tools import execution, views


def test_execution_and_view_handlers_live_in_domain_modules() -> None:
    assert execution.execute_code.__module__ == "freecad_mcp.tools.execution"
    assert execution.execute_code_async.__module__ == "freecad_mcp.tools.execution"
    assert views.get_view.__module__ == "freecad_mcp.tools.views"


def test_execution_and_view_handlers_are_registered() -> None:
    registered = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert {"execute_code", "execute_code_async", "get_view"} <= registered
