"""A blocking, thread-safe connection to one MCP server.

The MCP SDK is asyncio based while workflow agents run in plain threads. Each connection owns a
daemon thread running an event loop; a single long-lived task opens the transport and session
(so the SDK's cancel scopes are entered and exited in the same task) and then waits to be told to
stop. Callers use :meth:`list_tools` / :meth:`call_tool`, which block until the call completes.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import DevFlowError
from app.mcp_tools.config import McpServerSpec, expand_env

logger = logging.getLogger(__name__)


class McpError(DevFlowError):
    status_code = 502


@dataclass
class RemoteTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    destructive: bool


@dataclass
class RawToolResult:
    text: str
    is_error: bool
    non_text_blocks: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _open_client(spec: McpServerSpec) -> AbstractAsyncContextManager:
    from mcp import Client, StdioServerParameters

    if spec.transport == "stdio":
        params = StdioServerParameters(
            command=expand_env(spec.command or ""),
            args=[expand_env(a) for a in spec.args],
            env={k: expand_env(v) for k, v in spec.env.items()} or None,  # the SDK adds a minimal safe base env
            cwd=spec.cwd,
        )
        return Client(params)
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    http = create_mcp_http_client(headers={k: expand_env(v) for k, v in spec.headers.items()} or None)
    return Client(streamable_http_client(expand_env(spec.url or ""), http_client=http))


class ServerConnection:
    def __init__(self, spec: McpServerSpec, *, connect_timeout: float = 30.0) -> None:
        self.spec = spec
        self.connect_timeout = connect_timeout
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name=f"mcp-{spec.name}", daemon=True)
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._client: Any = None
        self._error: BaseException | None = None
        self._serve_future = None
        self._closed = False

    # -- lifecycle ----------------------------------------------------------------------------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _serve(self) -> None:
        self._stop = asyncio.Event()
        try:
            async with _open_client(self.spec) as client:
                self._client = client
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - reported to the caller thread
            self._error = exc
        finally:
            self._client = None
            self._ready.set()

    def start(self) -> None:
        self._thread.start()
        self._serve_future = asyncio.run_coroutine_threadsafe(self._serve(), self._loop)
        if not self._ready.wait(self.connect_timeout):
            self.close()
            raise McpError(f"MCP server '{self.spec.name}' did not start within {self.connect_timeout:.0f}s")
        if self._client is None:
            detail = _describe(self._error)
            self.close()
            raise McpError(f"Could not connect to MCP server '{self.spec.name}': {detail}")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._stop is not None:
                self._loop.call_soon_threadsafe(self._stop.set)
            if self._serve_future is not None:
                try:
                    self._serve_future.result(timeout=10)
                except Exception:  # noqa: BLE001 - shutting down; transport errors are irrelevant now
                    pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread.is_alive():
                self._thread.join(timeout=5)
            if not self._loop.is_running():
                self._loop.close()

    # -- calls ----------------------------------------------------------------------------------

    def _run(self, coro, timeout: float):
        if self._client is None:
            coro.close()
            raise McpError(f"MCP server '{self.spec.name}' is not connected")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise McpError(f"MCP call to '{self.spec.name}' timed out after {timeout:.0f}s") from exc
        except McpError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise McpError(f"MCP call to '{self.spec.name}' failed: {_describe(exc)}") from exc

    def list_tools(self, timeout: float = 30.0) -> list[RemoteTool]:
        async def go() -> list[RemoteTool]:
            tools: list[RemoteTool] = []
            cursor = None
            while True:
                page = await self._client.list_tools(cursor=cursor)
                for tool in page.tools:
                    ann = getattr(tool, "annotations", None)
                    tools.append(RemoteTool(
                        name=tool.name, description=(tool.description or "").strip(),
                        input_schema=getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {},
                        read_only=bool(getattr(ann, "read_only_hint", None) is True),
                        destructive=bool(getattr(ann, "destructive_hint", None) is True),
                    ))
                cursor = getattr(page, "next_cursor", None)
                if not cursor:
                    return tools

        return self._run(go(), timeout)

    def call_tool(self, name: str, arguments: dict[str, Any], timeout: float = 60.0) -> RawToolResult:
        async def go() -> RawToolResult:
            result = await self._client.call_tool(name, arguments)
            texts: list[str] = []
            other = 0
            for block in result.content or []:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    texts.append(text)
                else:
                    other += 1
            if not texts and getattr(result, "structured_content", None):
                import json

                texts.append(json.dumps(result.structured_content, default=str))
            return RawToolResult("\n".join(texts), bool(result.is_error), other)

        return self._run(go(), timeout)


def _describe(exc: BaseException | None) -> str:
    if exc is None:
        return "unknown error"
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(_describe(e) for e in exc.exceptions)
    return f"{type(exc).__name__}: {exc}"[:500]
