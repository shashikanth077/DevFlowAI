"""MCP server specifications.

Two sources, deliberately different in trust:

* the built-in ``devflow-repo`` server (our own code, read-only, bound to one workflow workspace);
* servers listed in the administrator's ``MCP_SERVERS_FILE``. A stdio entry is a command that is
  executed on the backend host, so it can only come from this operator-controlled file and
  never from the API or the dashboard. Users can only switch listed servers on or off.

The file accepts either ``{"servers": [...]}`` or the ``{"mcpServers": {name: {...}}}`` layout
used by Claude Desktop / Claude Code, so existing configurations can be reused.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.core.config import Settings

logger = logging.getLogger(__name__)

AGENT_NAMES = (
    "requirement_analyst", "repository_analyst", "architect", "task_orchestrator", "frontend_developer",
    "backend_developer", "qa_engineer", "code_reviewer", "release_engineer",
)
# Agents that may use tools at all. Release/QA/orchestrator stay deterministic on purpose.
TOOL_CAPABLE_AGENTS = ("requirement_analyst", "architect", "frontend_developer", "backend_developer", "code_reviewer")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
BUILTIN_REPO_SERVER = "devflow-repo"
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: str) -> str:
    """Expand ``${VAR}`` from the host environment (only variables explicitly referenced are exposed)."""
    return _VAR_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)


class McpServerSpec(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,48}$")
    description: str = ""
    transport: Literal["stdio", "http"] = "stdio"
    # stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    # http (streamable HTTP)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    # policy
    agents: list[str] = Field(default_factory=list, description="Empty = every tool-capable agent")
    tools_allow: list[str] = Field(default_factory=list, description="Tools allowed even if not marked read-only")
    tools_deny: list[str] = Field(default_factory=list)
    allow_write_tools: bool = False
    builtin: bool = False

    @field_validator("agents")
    @classmethod
    def _known_agents(cls, agents: list[str]) -> list[str]:
        unknown = [a for a in agents if a not in TOOL_CAPABLE_AGENTS]
        if unknown:
            raise ValueError(f"Unknown or non-tool agents: {unknown}; allowed: {list(TOOL_CAPABLE_AGENTS)}")
        return agents

    @model_validator(mode="after")
    def _transport_fields(self) -> McpServerSpec:
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio servers need a 'command'")
        if self.transport == "http":
            parsed = urlparse(self.url or "")
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if not (parsed.scheme == "https" or (parsed.scheme == "http" and local)) or not parsed.hostname:
                raise ValueError("http servers need an https:// URL (plain http only for localhost)")
        return self

    def allowed_for(self, agent: str) -> bool:
        return agent in (self.agents or TOOL_CAPABLE_AGENTS)

    def public(self) -> dict:
        """Safe description for the API: never includes env values, headers or command lines."""
        return {
            "name": self.name, "description": self.description, "transport": self.transport,
            "builtin": self.builtin, "agents": self.agents or list(TOOL_CAPABLE_AGENTS),
            "allow_write_tools": self.allow_write_tools,
        }


def builtin_repo_spec(workspace: Path) -> McpServerSpec:
    """The repository tool server, scoped to a single workflow workspace."""
    return McpServerSpec(
        name=BUILTIN_REPO_SERVER, builtin=True, transport="stdio",
        description="Read-only repository tools: list, read and search files, git log/status/diff.",
        command=sys.executable,
        args=["-m", "app.mcp_tools.repo_server", "--workspace", str(workspace)],
        cwd=str(BACKEND_ROOT), env={"PYTHONPATH": str(BACKEND_ROOT)},
        agents=["architect", "frontend_developer", "backend_developer", "code_reviewer"],
    )


def load_external_specs(settings: Settings) -> tuple[list[McpServerSpec], list[str]]:
    """Load the operator's MCP server file. Returns ``(specs, errors)``; a bad entry never aborts the rest."""
    path = settings.mcp_servers_file
    if not path:
        return [], []
    errors: list[str] = []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"Cannot read MCP_SERVERS_FILE '{path}': {exc}"]
    entries: list[dict]
    if isinstance(raw, dict) and isinstance(raw.get("mcpServers"), dict):
        entries = [{"name": n, **cfg} for n, cfg in raw["mcpServers"].items() if isinstance(cfg, dict)]
    elif isinstance(raw, dict) and isinstance(raw.get("servers"), list):
        entries = [e for e in raw["servers"] if isinstance(e, dict)]
    else:
        return [], [f"MCP_SERVERS_FILE '{path}' must contain 'servers' (list) or 'mcpServers' (object)"]
    specs: list[McpServerSpec] = []
    seen: set[str] = set()
    for entry in entries:
        entry = dict(entry)
        if "type" in entry and "transport" not in entry:  # Claude-style {"type": "http", "url": ...}
            entry["transport"] = "http" if entry.pop("type") in ("http", "sse", "streamable-http") else "stdio"
        if "url" in entry and "transport" not in entry and "command" not in entry:
            entry["transport"] = "http"
        try:
            spec = McpServerSpec.model_validate(entry)
        except ValidationError as exc:
            errors.append(f"Server '{entry.get('name', '?')}': {exc.errors()[0]['msg']}")
            continue
        if spec.name in seen or spec.name == BUILTIN_REPO_SERVER:
            errors.append(f"Server name '{spec.name}' is duplicated or reserved")
            continue
        seen.add(spec.name)
        specs.append(spec)
    return specs, errors


def resolve_specs(settings: Settings, workspace: Path | None) -> tuple[list[McpServerSpec], list[str]]:
    specs, errors = load_external_specs(settings)
    if settings.mcp_builtin_repo_server and workspace is not None:
        specs.insert(0, builtin_repo_spec(workspace))
    return specs, errors
