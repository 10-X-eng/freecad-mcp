"""MCP tools for managing FreeCAD documents."""

from mcp.types import TextContent

from .. import server_state
from ..mcp_compat import Context
from ..operations import (
    create_document_operation,
    list_documents_operation,
    reload_document_operation,
)


def create_document(ctx: Context, name: str) -> list[TextContent]:
    """Create a new document in FreeCAD.

    Args:
        name: The name of the document to create.

    Returns:
        A message indicating the success or failure of the document creation.

    Examples:
        If you want to create a document named "MyDocument", you can use the following data.
        ```json
        {
            "name": "MyDocument"
        }
        ```
    """
    return create_document_operation(server_state.get_freecad_connection(), name)


def reload_document(ctx: Context, doc_name: str) -> list[TextContent]:
    """Close and re-open a document to pick up external file changes.

    Use this AFTER the document's .FCStd file has been modified by
    something outside of FreeCAD's GUI process — for example, a
    headless `freecadcmd` script that edited and saved the file. The
    open GUI document is otherwise unaware of on-disk changes; this
    tool closes the stale in-memory copy and reopens the file from
    disk so the GUI shows current geometry.

    Args:
        doc_name: The name of the open document to reload. Must match
            the name shown by ``list_documents``.

    Returns:
        A message confirming the document was reloaded, or describing
        the failure (document not loaded, no associated file, etc).

    Examples:
        ```json
        {
            "doc_name": "chassis"
        }
        ```
    """
    return reload_document_operation(server_state.get_freecad_connection(), doc_name)


def list_documents(ctx: Context) -> list[TextContent]:
    """Get the list of open documents in FreeCAD.

    Returns:
        A list of document names.
    """
    return list_documents_operation(server_state.get_freecad_connection())
