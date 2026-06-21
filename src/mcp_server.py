"""Backward-compatible wrapper for the packaged SGGS MCP server."""

from sggs_mcp.server import *  # noqa: F401,F403
from sggs_mcp.server import mcp


if __name__ == "__main__":
    mcp.run(transport="stdio")
