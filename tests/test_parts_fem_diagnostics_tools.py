import asyncio

from freecad_mcp.server import mcp
from freecad_mcp.tools import diagnostics, fem, parts_library


EXPECTED_MODULES = {
    "insert_part_from_library": parts_library,
    "get_parts_list": parts_library,
    "get_rpc_status": diagnostics,
    "run_fem_analysis": fem,
}


def test_handlers_live_in_domain_modules() -> None:
    for name, module in EXPECTED_MODULES.items():
        assert getattr(module, name).__module__ == module.__name__


def test_handlers_are_registered() -> None:
    registered = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert EXPECTED_MODULES.keys() <= registered
