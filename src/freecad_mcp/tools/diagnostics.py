"""MCP tools for diagnosing the FreeCAD RPC bridge."""

from mcp.types import TextContent

from .. import server_state
from ..mcp_compat import Context
from ..operations import get_rpc_status_operation


def get_rpc_status(ctx: Context) -> list[TextContent]:
    """Get RPC and FreeCAD GUI-dispatch health.

    This tool does not use FreeCAD's GUI thread, so it remains available after
    a GUI operation times out. A ``stuck`` state identifies the operation that
    is still running and indicates that FreeCAD may need to be restarted.
    """
    return get_rpc_status_operation(server_state.get_freecad_connection())
