"""A small MCP server used to test the broker's policy decisions over a real transport."""
import sys
import time

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("policy-test")


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def safe_read(text: str, repeat: int = 1) -> str:
    """Echo text (read-only)."""
    return text * repeat


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def leak() -> str:
    """Returns a credential-looking string (read-only)."""
    return "config: token=ghp_" + "q" * 36 + " and password = \"hunter2hunter2\""


@server.tool()
def write_thing(name: str) -> str:
    """Pretends to write something; no annotations, so it is not provably read-only."""
    return f"wrote {name}"


@server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True))
def danger() -> str:
    """Destructive tool."""
    return "boom"


@server.tool()
def allowlisted_write() -> str:
    """Not read-only, but the operator allow-lists it."""
    return "ok-allowlisted"


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def slow(seconds: float) -> str:
    """Sleeps."""
    time.sleep(seconds)
    return "done"


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def fails() -> str:
    """Always errors."""
    raise ValueError("deliberate failure")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run("stdio")
