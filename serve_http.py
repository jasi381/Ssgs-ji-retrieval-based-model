"""Prefect Cloud entrypoint — runs SGGS MCP server over HTTP."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from sggs_mcp.cli import run_server_http  # noqa: E402


def serve():
    run_server_http()
