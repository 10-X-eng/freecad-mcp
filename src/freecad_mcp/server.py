"""FreeCAD MCP server composition and command-line entry point."""

import argparse
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import validators

from .mcp_compat import FastMCP
from .prompt_text import ASSET_CREATION_STRATEGY
from .server_state import disconnect_freecad, get_freecad_connection, state
from .tools.diagnostics import get_rpc_status
from .tools.documents import create_document, list_documents, reload_document
from .tools.execution import execute_code, execute_code_async
from .tools.fem import run_fem_analysis
from .tools.objects import create_object, delete_object, edit_object, get_object, get_objects
from .tools.parts_library import get_parts_list, insert_part_from_library
from .tools.views import get_view


logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("FreeCADMCPserver")
logger.setLevel(logging.INFO)


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
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
mcp.tool(structured_output=False)(insert_part_from_library)
mcp.tool(structured_output=False)(get_objects)
mcp.tool(structured_output=False)(get_object)
mcp.tool(structured_output=False)(get_parts_list)
mcp.tool(structured_output=False)(reload_document)
mcp.tool(structured_output=False)(list_documents)
mcp.tool(structured_output=False)(get_rpc_status)
mcp.tool(structured_output=False)(run_fem_analysis)


@mcp.prompt()
def asset_creation_strategy() -> str:
    return ASSET_CREATION_STRATEGY


def _validate_host(value: str) -> str:
    """Validate that *value* is a valid IP address or hostname.

    Used as the ``type`` callback for the ``--host`` argparse argument.
    Raises ``argparse.ArgumentTypeError`` on invalid input.
    """
    if validators.ipv4(value) or validators.ipv6(value) or validators.hostname(value):
        return value
    raise argparse.ArgumentTypeError(
        f"Invalid host: '{value}'. Must be a valid IP address or hostname."
    )


def main() -> None:
    """Run the MCP server."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only-text-feedback",
        action="store_true",
        help="Only return text feedback",
    )
    parser.add_argument(
        "--host",
        type=_validate_host,
        default="localhost",
        help="Host address of the FreeCAD RPC server to connect to (default: localhost)",
    )
    args = parser.parse_args()
    state.only_text_feedback = args.only_text_feedback
    state.rpc_host = args.host
    logger.info(f"Only text feedback: {state.only_text_feedback}")
    logger.info(f"Connecting to FreeCAD RPC server at: {state.rpc_host}")
    mcp.run()
