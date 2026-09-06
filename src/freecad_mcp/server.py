"""Small MCP surface: Python execution, image transport, and bridge health."""

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from typing import Annotated, Literal

from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import Field
import validators

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP

from .freecad_client import FreeCADConnection
from .help_content import HelpTopic, get_help_content
from .responses import execution_feedback, runtime_feedback
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
    lifespan=lifespan,
    instructions=(
        "Control FreeCAD with the exact tool names exposed by the client. Start with "
        "GetHelp(topic='start'); never invent or rewrite a tool name. Use the returned "
        "related topics as needed."
    ),
)


@mcp.tool(name="GetHelp", structured_output=False)
async def get_help(topic: HelpTopic = "start") -> CallToolResult:
    """Get focused operating guidance. Start with topic=start. Other topics:
    python, documents, workbenches, inspection, validation, fem, cam, blocked.
    """
    return CallToolResult(content=[TextContent(
        type="text",
        text=json.dumps(get_help_content(topic), ensure_ascii=False, separators=(",", ":")),
    )])


def json_result(data: dict, *, status=False) -> CallToolResult:
    feedback = runtime_feedback(data) if status else execution_feedback(data)
    return CallToolResult(
        isError=not data.get("success", True),
        content=[TextContent(type="text", text=json.dumps(feedback, ensure_ascii=False, separators=(",", ":")))],
    )


async def rpc_call(method, *args, status=False) -> CallToolResult:
    try:
        return json_result(await asyncio.to_thread(method, *args), status=status)
    except Exception as exc:
        return json_result({
            "success": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        })


@mcp.tool(name="DocumentOperations", structured_output=False)
async def document_operations(
    action: Literal["list", "new", "open", "activate", "save", "save_as", "reload", "close"],
    document: str | None = None,
    path: str | None = None,
    discard_changes: bool = False,
    overwrite: bool = False,
) -> CallToolResult:
    """Manage live .FCStd documents: list; new(document); open(path);
    activate/save/reload/close(document or active); save_as(path). reload/close
    require discard_changes=true when modified; save_as requires overwrite=true
    before replacing another file.
    """
    return await rpc_call(
        connection().document_operations,
        action, document, path, discard_changes, overwrite,
    )


@mcp.tool(name="ExecutePython", structured_output=False)
async def execute_python(
    code: Annotated[str, Field(max_length=100_000)],
    timeout_seconds: Annotated[int, Field(ge=1, le=3600)] = 90,
) -> CallToolResult:
    """Run Python in live FreeCAD with App and Gui preloaded.

    Imports/variables persist and are shared by clients. Return the last
    expression or assign _result; _ holds the previous result. Use dir()/help()
    to explore the API and doc.recompute() after edits. Errors include source
    tracebacks but do not undo changes. Timeout stops waiting, not running
    code: check GetRuntimeStatus before retrying. Full host privileges.
    """
    return await rpc_call(connection().execute_python, code, timeout_seconds)


@mcp.tool(name="InspectDocument", structured_output=False)
async def inspect_document(
    document: str | None = None,
    object_name: str | None = None,
    properties: list[str] | None = None,
    max_depth: Annotated[int, Field(ge=1, le=10)] = 6,
) -> CallToolResult:
    """Inspect the active live document without changing it. With no
    object_name, return its compact native GUI tree. With object_name, return
    hierarchy, dependencies and property names; request selected property
    values with properties. Internal object names are used, not labels.
    """
    return await rpc_call(
        connection().inspect_document,
        document, object_name, properties, max_depth,
    )


@mcp.tool(name="GetView", structured_output=False)
async def get_view(
    width: Annotated[int, Field(ge=1, le=4096)] = 1024,
    height: Annotated[int, Field(ge=1, le=4096)] = 768,
) -> CallToolResult:
    """Capture the current 3D view as PNG without changing camera or selection.
    Orient/frame with ExecutePython first, for example:
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


@mcp.tool(name="GetRuntimeStatus", structured_output=False)
async def get_runtime_status() -> CallToolResult:
    """Read FreeCAD version, session identity, GUI state and test-worker state.
    Responds while GUI Python is busy. If stuck, wait or restart FreeCAD;
    restarting loses live variables. A changed session_id also means they reset.
    """
    return await rpc_call(connection().get_runtime_status, status=True)


@mcp.tool(name="TestPython", structured_output=False)
async def test_python(
    code: Annotated[str, Field(max_length=100_000)],
    document_path: str | None = None,
    timeout_seconds: Annotated[int, Field(ge=1, le=3600)] = 60,
) -> CallToolResult:
    """Run Python/assertions in a fresh, matching FreeCADCmd with App, but no Gui
    or live variables. Return the last expression or assign _result. An optional
    absolute document_path opens a saved .FCStd copy as doc, excluding unsaved
    edits. Timeout kills the worker. Temporary files are discarded; return data.
    Filesystem/network access is NOT sandboxed.
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
