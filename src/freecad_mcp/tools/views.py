"""MCP tools for viewing FreeCAD models."""

from mcp.types import ImageContent, TextContent

from .. import server_state
from ..mcp_compat import Context
from ..operations import get_view_operation
from .types import ViewName


def get_view(
    ctx: Context,
    view_name: ViewName,
    width: int | None = None,
    height: int | None = None,
    focus_object: str | None = None,
) -> list[ImageContent | TextContent]:
    """Get a screenshot of the active view.

    Args:
        view_name: The name of the view to get the screenshot of.
        The following views are available:
        - "Isometric"
        - "Front"
        - "Top"
        - "Right"
        - "Back"
        - "Left"
        - "Bottom"
        - "Dimetric"
        - "Trimetric"
        width: The width of the screenshot in pixels. If not specified, uses the viewport width.
        height: The height of the screenshot in pixels. If not specified, uses the viewport height.
        focus_object: The name of the object to focus on. If not specified, fits all objects in the view.

    Returns:
        A screenshot of the active view.
    """
    return get_view_operation(
        server_state.get_freecad_connection(), view_name, width, height, focus_object
    )
