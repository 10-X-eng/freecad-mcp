"""Small MCP surface: Python execution, image transport, and bridge health."""

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from typing import Annotated

from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import Field
import validators

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP

from .freecad_client import FreeCADConnection
from .server_state import ServerState

logger = logging.getLogger("FreeCADMCPserver")
state = ServerState()


def connection() -> FreeCADConnection:
    if state.freecad_connection is None:
        state.freecad_connection = FreeCADConnection(state.rpc_host, state.rpc_port)
    return state.freecad_connection


@asynccontextmanager
async def lifespan(_server):
    try:
        await asyncio.to_thread(connection().ping)
    except Exception as exc:
        logger.warning("Start the matching FreeCAD addon before using tools: %s", exc)
    try:
        yield
    finally:
        state.freecad_connection = None


mcp = FastMCP(
    "FreeCADMCP",
    log_level="WARNING",
    instructions=(
        "Write Python to control FreeCAD. App/FreeCAD and Gui/FreeCADGui are "
        "preloaded; imports, variables and functions persist between execute_python "
        "calls in this FreeCAD process (shared by connected clients). Use dir(), "
        "help(), obj.PropertiesList and small result dictionaries to inspect the API. "
        "Import Part, Sketcher, Draft, ObjectsFem and other workbench modules as needed. "
        "Call doc.recompute() after modeling changes; assert geometry and dimensions. "
        "Use Python to orient/frame the view, then get_view for a PNG. Correct code "
        "using returned tracebacks. Changes before an exception remain applied; no "
        "automatic rollback. A live timeout does not cancel running code: check "
        "get_runtime_status before retrying. Code runs with FreeCAD's full privileges."
        " Use test_python to check scripts/assertions in a fresh, disposable headless "
        "FreeCAD process. It cannot access the live namespace, unsaved state or Gui. "
        "When a saved document is supplied, doc refers to its temporary copy."
    ),
    lifespan=lifespan,
)


def json_result(data: dict) -> CallToolResult:
    return CallToolResult(
        isError=not data.get("success", True),
        content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
    )


async def rpc_call(method, *args) -> CallToolResult:
    try:
        return json_result(await asyncio.to_thread(method, *args))
    except Exception as exc:
        return json_result({
            "success": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        })


@mcp.tool(structured_output=False)
async def execute_python(
    code: Annotated[str, Field(max_length=100_000)],
    timeout_seconds: Annotated[int, Field(ge=1, le=3600)] = 90,
) -> CallToolResult:
    """Execute a Python cell on FreeCAD's GUI thread.

    Imports, variables and functions persist. The final expression is returned
    as result, or assign _result explicitly when the cell ends in a statement.
    _ holds the last successful result. Native lists/dicts/scalars are JSON;
    other objects return type/repr. Select CAD properties explicitly in Python.

    Returns cell/session IDs, bounded stdout/stderr, result and elapsed time.
    Failures include the exception type and traceback with cell source lines.
    App/FreeCAD and Gui/FreeCADGui aliases are restored before each call.
    Use Python assertions to test geometry and get_view for visual verification.

    timeout_seconds limits the wait, not execution. Running live code cannot be
    safely force-cancelled. Use get_runtime_status after a timeout.
    """
    return await rpc_call(connection().execute_python, code, timeout_seconds)


@mcp.tool(structured_output=False)
async def get_view(
    width: Annotated[int, Field(ge=1, le=4096)] = 1024,
    height: Annotated[int, Field(ge=1, le=4096)] = 768,
) -> CallToolResult:
    """Return a PNG of the current 3D view, without changing camera or selection.

    Set orientation/zoom in Python first, for example:
    Gui.activeDocument().activeView().viewIsometric()
    Gui.activeDocument().activeView().fitAll()
    """
    try:
        png = await asyncio.to_thread(connection().get_view, width, height)
        return CallToolResult(content=[ImageContent(type="image", data=png, mimeType="image/png")])
    except Exception as exc:
        return json_result({
            "success": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        })


@mcp.tool(structured_output=False)
async def get_runtime_status() -> CallToolResult:
    """Report FreeCAD version, current/recent cells and GUI dispatch health.

    Uses a separate connection and no GUI dispatch, so it remains responsive
    while Python is running or stuck. A stuck task may finish and recover;
    restart FreeCAD manually if it does not. Restarting loses session variables.
    """
    return await rpc_call(connection().get_runtime_status)


@mcp.tool(structured_output=False)
async def test_python(
    code: Annotated[str, Field(max_length=100_000)],
    document_path: str | None = None,
    timeout_seconds: Annotated[int, Field(ge=1, le=3600)] = 60,
) -> CallToolResult:
    """Test Python and assertions in a disposable FreeCADCmd of the same version.

    A fresh process, profile and temporary workspace are used for every call
    on the FreeCAD host. App/FreeCAD are available; Gui and the live namespace
    are not. Optionally pass the absolute path of a saved .FCStd; a copy is
    opened as doc. Unsaved live edits are not included. Files in the temporary
    workspace are discarded, so return results rather than artifact paths.

    Returns the same result/stdout/stderr/traceback fields as execute_python,
    plus FreeCAD version, process logs, exit status and timeout status. The
    process is terminated on timeout. One test may run at a time; status and
    live execution stay available. This is process isolation, not a security
    sandbox: arbitrary Python still has the host user's filesystem/network access.
    """
    return await rpc_call(connection().test_python, code, document_path, timeout_seconds)


def _validate_host(value: str) -> str:
    if validators.ipv4(value) or validators.ipv6(value) or validators.hostname(value):
        return value
    raise argparse.ArgumentTypeError(f"Invalid host: {value!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Control FreeCAD through Python")
    parser.add_argument("--host", type=_validate_host, default="localhost")
    parser.add_argument("--port", type=int, default=9875)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    state.rpc_host, state.rpc_port = args.host, args.port
    logging.basicConfig(level=logging.WARNING)
    mcp.run()
