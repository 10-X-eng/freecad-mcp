import asyncio

from freecad_mcp.server import mcp
from freecad_mcp.tools import objects


OBJECT_TOOL_NAMES = {
    "create_object",
    "edit_object",
    "delete_object",
    "get_objects",
    "get_object",
}


def test_object_handlers_live_in_object_module() -> None:
    for name in OBJECT_TOOL_NAMES:
        assert getattr(objects, name).__module__ == "freecad_mcp.tools.objects"


def test_object_handlers_are_registered() -> None:
    registered = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert OBJECT_TOOL_NAMES <= registered
