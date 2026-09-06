"""Compatibility imports for supported MCP package versions."""

try:
    # mcp 1.x
    from mcp.server.fastmcp import Context, FastMCP
except ImportError:
    # mcp 2.x moved mcp.server.fastmcp to mcp.server.mcpserver and renamed
    # FastMCP to MCPServer; the API surface used here is unchanged.
    from mcp.server.mcpserver import Context
    from mcp.server.mcpserver import MCPServer as FastMCP

__all__ = ["Context", "FastMCP"]
