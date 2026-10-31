"""Connects agents to the MCP servers over stdio. The offline kit needs nothing beyond this machine."""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from typing import Iterator

from mcp import StdioServerParameters, stdio_client
from strands.tools.mcp import MCPClient
from strands.types.exceptions import MCPClientInitializationError


def client(server: str) -> MCPClient:
    params = StdioServerParameters(command=sys.executable, args=["-m", f"emerald.mcp_servers.{server}"], env=dict(os.environ))
    return MCPClient(lambda: stdio_client(params), startup_timeout=60)


@contextmanager
def connected(*servers: str) -> Iterator[list]:
    """Start the named servers and yield their tools; they stop when the block ends."""
    clients = [client(name) for name in servers]
    started: list[MCPClient] = []
    try:
        tools: list = []
        for index, mcp_client in enumerate(clients):
            try:
                mcp_client.start()
            except MCPClientInitializationError:
                # A busy machine can make a server miss its start window. Try once more with a fresh process.
                time.sleep(2)
                mcp_client = clients[index] = client(servers[index])
                mcp_client.start()
            started.append(mcp_client)
            tools.extend(mcp_client.list_tools_sync())
        yield tools
    finally:
        for mcp_client in reversed(started):
            mcp_client.stop(None, None, None)
