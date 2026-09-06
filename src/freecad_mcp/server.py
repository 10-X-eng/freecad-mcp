import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

from mcp.types import ImageContent, TextContent

from .mcp_compat import Context, FastMCP
from .operations import (
    get_parts_list_operation,
    get_rpc_status_operation,
    insert_part_from_library_operation,
    run_fem_analysis_operation,
)
from .prompt_text import ASSET_CREATION_STRATEGY
from .server_state import disconnect_freecad, get_freecad_connection, state
from .tools.documents import create_document, list_documents, reload_document
from .tools.execution import execute_code, execute_code_async
from .tools.objects import create_object, delete_object, edit_object, get_object, get_objects
from .tools.types import ViewName
from .tools.views import get_view


logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("FreeCADMCPserver")
logger.setLevel(logging.INFO)


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    try:
        logger.info("FreeCADMCP server starting up")
        try:
            get_freecad_connection()
            logger.info("Successfully connected to FreeCAD on startup")
        except Exception as e:
            logger.warning(f"Could not connect to FreeCAD on startup: {str(e)}")
            logger.warning(
                "Make sure the FreeCAD addon is running before using FreeCAD resources or tools"
            )
        yield {}
    finally:
        if state.freecad_connection:
            logger.info("Disconnecting from FreeCAD on shutdown")
            disconnect_freecad()
        logger.info("FreeCADMCP server shut down")


mcp = FastMCP(
    "FreeCADMCP",
    instructions="FreeCAD integration through the Model Context Protocol",
    lifespan=server_lifespan,
)


mcp.tool(structured_output=False)(create_document)


mcp.tool(structured_output=False)(create_object)


mcp.tool(structured_output=False)(edit_object)


mcp.tool(structured_output=False)(delete_object)


mcp.tool(structured_output=False)(execute_code_async)


mcp.tool(structured_output=False)(execute_code)


mcp.tool(structured_output=False)(get_view)


@mcp.tool(structured_output=False)
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
        get_freecad_connection(),
        state.only_text_feedback,
        relative_path,
        include_screenshot,
        view_name,
    )


mcp.tool(structured_output=False)(get_objects)


mcp.tool(structured_output=False)(get_object)


@mcp.tool(structured_output=False)
def get_parts_list(ctx: Context) -> list[TextContent]:
    """Get the list of parts in the parts library addon.
    """
    return get_parts_list_operation(get_freecad_connection())


mcp.tool(structured_output=False)(reload_document)


mcp.tool(structured_output=False)(list_documents)


@mcp.tool(structured_output=False)
def get_rpc_status(ctx: Context) -> list[TextContent]:
    """Get RPC and FreeCAD GUI-dispatch health.

    This tool does not use FreeCAD's GUI thread, so it remains available after
    a GUI operation times out. A ``stuck`` state identifies the operation that
    is still running and indicates that FreeCAD may need to be restarted.
    """
    return get_rpc_status_operation(get_freecad_connection())


@mcp.tool(structured_output=False)
def run_fem_analysis(
    ctx: Context,
    doc_name: str,
    analysis_name: str,
    timeout: int = 600,
    include_screenshot: bool = True,
    view_name: ViewName = "Isometric",
) -> list[TextContent | ImageContent]:
    """Run the CalculiX solver on an existing Fem::FemAnalysis container and return summary results.

    Prerequisites in the document:
    - A Part-derived solid (e.g. Part::Box, PartDesign::Body) acting as the geometry.
    - A Fem::AnalysisPython container created via `create_object`.
    - A Fem::MaterialCommon assigned to the geometry, added to the analysis.
    - A Fem::FemMeshGmsh referencing the geometry, added to the analysis (the
      mesh is generated automatically when created via `create_object`).
    - At least one Fem::ConstraintFixed and one Fem::ConstraintForce (or
      ConstraintPressure) bound to faces of the geometry, added to the analysis.

    A SolverCcxTools is auto-created if the analysis has none.

    The solver runs synchronously on the FreeCAD GUI thread and blocks all
    other RPC calls for its duration; do not fan out parallel requests.

    Returns max von Mises stress (MPa), max/min displacement (mm), node count,
    and the working directory CalculiX wrote to. On failure, returns the
    prerequisite-check or solver error along with the working directory for
    triage.

    Args:
        doc_name: Name of the FreeCAD document.
        analysis_name: Name of the Fem::AnalysisPython object.
        timeout: Seconds to wait for the solver (default 600).
        include_screenshot: Whether to return a screenshot of the model (default True).
            Set to False to save tokens when only the numeric results are needed.
        view_name: The view orientation of the returned screenshot (default "Isometric").
    """
    return run_fem_analysis_operation(
        get_freecad_connection(),
        state.only_text_feedback,
        doc_name,
        analysis_name,
        timeout,
        include_screenshot,
        view_name,
    )


@mcp.prompt()
def asset_creation_strategy() -> str:
    return ASSET_CREATION_STRATEGY


def _validate_host(value: str) -> str:
    """Validate that *value* is a valid IP address or hostname.

    Used as the ``type`` callback for the ``--host`` argparse argument.
    Raises ``argparse.ArgumentTypeError`` on invalid input.
    """
    import argparse

    import validators

    if validators.ipv4(value) or validators.ipv6(value) or validators.hostname(value):
        return value
    raise argparse.ArgumentTypeError(
        f"Invalid host: '{value}'. Must be a valid IP address or hostname."
    )


def main():
    """Run the MCP server"""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--only-text-feedback", action="store_true", help="Only return text feedback")
    parser.add_argument("--host", type=_validate_host, default="localhost", help="Host address of the FreeCAD RPC server to connect to (default: localhost)")
    args = parser.parse_args()
    state.only_text_feedback = args.only_text_feedback
    state.rpc_host = args.host
    logger.info(f"Only text feedback: {state.only_text_feedback}")
    logger.info(f"Connecting to FreeCAD RPC server at: {state.rpc_host}")
    mcp.run()
