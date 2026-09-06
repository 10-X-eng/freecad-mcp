"""MCP tools for executing Python code in FreeCAD."""

from mcp.types import ImageContent, TextContent

from .. import server_state
from ..mcp_compat import Context
from ..operations import execute_code_async_operation, execute_code_operation
from .types import ViewName


def execute_code_async(ctx: Context, code: str) -> list[TextContent]:
    """Execute Python code in FreeCAD without waiting for completion.

    Use this ONLY for long-running background computations that do NOT touch the
    FreeCAD GUI or mutate the FreeCAD document tree directly.

    This tool runs the submitted code in a background thread and returns
    immediately. Because it does not run on FreeCAD's main GUI thread, the code
    must NOT call FreeCADGui APIs, manipulate the active view or selection, create
    or edit document objects, change object properties, call doc.recompute(), or
    save documents.

    For code that touches FreeCAD documents, document objects, FreeCADGui, the
    active view, selection, recompute, or save operations, use execute_code instead.
    execute_code runs on the FreeCAD GUI thread and is the safe default for normal
    FreeCAD automation.

    Use execute_code_async only for background-safe work such as long-running
    pure OCCT geometry calculations (e.g. fuse/cut/loft on already-fetched shapes)
    or other CPU-bound computations that do not interact with the document or GUI.

    Typical usage pattern:
    1. Fetch shapes into local variables first (via execute_code on the GUI thread).
    2. Store intermediate results in a module-level Python variable (not in the
       FreeCAD document) so execute_code can read them later.
    3. Run the heavy computation via execute_code_async.
    4. After the expected computation time has elapsed, apply results to the
       document via execute_code (which runs on the GUI thread).

    Args:
        code: Background-safe Python code to execute.

    Returns:
        A message confirming that background execution has started.
    """
    return execute_code_async_operation(server_state.get_freecad_connection(), code)


def execute_code(
    ctx: Context,
    code: str,
    include_screenshot: bool = True,
    view_name: ViewName = "Isometric",
) -> list[TextContent | ImageContent]:
    """Execute arbitrary Python code in FreeCAD.

    Args:
        code: The Python code to execute.
        include_screenshot: Whether to return a screenshot of the model (default True).
            Set to False to save tokens when the code does not change the model's
            appearance, e.g. analytical or computational scripts whose result is
            printed output, or intermediate steps in a longer sequence of changes.
        view_name: The view orientation of the returned screenshot (default "Isometric").
            Pick the view that best shows the change being made.

    Returns:
        A message indicating the success or failure of the code execution, the output of the code execution, and a screenshot of the object.
    """
    return execute_code_operation(
        server_state.get_freecad_connection(),
        server_state.state.only_text_feedback,
        code,
        include_screenshot,
        view_name,
    )
