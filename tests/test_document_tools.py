import asyncio

from freecad_mcp.server import mcp
from freecad_mcp.tools import documents


def test_document_handlers_live_in_document_module() -> None:
    assert documents.create_document.__module__ == "freecad_mcp.tools.documents"
    assert documents.reload_document.__module__ == "freecad_mcp.tools.documents"
    assert documents.list_documents.__module__ == "freecad_mcp.tools.documents"


def test_document_handlers_are_registered() -> None:
    registered = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert {"create_document", "reload_document", "list_documents"} <= registered
