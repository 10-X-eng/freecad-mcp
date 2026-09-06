"""MCP tools for the FreeCAD parts library addon."""

from mcp.types import ImageContent, TextContent

from .. import server_state
from ..mcp_compat import Context
from ..operations import get_parts_list_operation, insert_part_from_library_operation
from .types import ViewName


def insert_part_from_library(
    ctx: Context,
    relative_path: str,
    include_screenshot: bool = True,
    view_name: ViewName = "Isometric",
) -> list[TextContent | ImageContent]:
    """Insert a part from the parts library addon.

    Args:
        relative_path: The relative path of the part to insert.
        include_screenshot: Whether to return a screenshot of the model (default True).
            Set to False to save tokens when visual feedback is not needed,
            e.g. for intermediate steps in a longer sequence of changes.
        view_name: The view orientation of the returned screenshot (default "Isometric").
            Pick the view that best shows the change being made.

    Returns:
        A message indicating the success or failure of the part insertion and a screenshot of the object.
    """
    return insert_part_from_library_operation(
        server_state.get_freecad_connection(),
        server_state.state.only_text_feedback,
        relative_path,
        include_screenshot,
        view_name,
    )


def get_parts_list(ctx: Context) -> list[TextContent]:
    """Get the list of parts in the parts library addon.
    """
    return get_parts_list_operation(server_state.get_freecad_connection())
