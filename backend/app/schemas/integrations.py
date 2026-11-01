from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LangSmithStatus(BaseModel):
    enabled: bool
    api_key_configured: bool
    project: str
    endpoint: str
    hide_content: bool
    redaction: str


class McpServerInfo(BaseModel):
    name: str
    description: str
    transport: str
    builtin: bool
    agents: list[str]
    allow_write_tools: bool
    enabled_for_user: bool


class McpStatus(BaseModel):
    available: bool  # server-wide MCP_ENABLED
    enabled_for_user: bool
    max_tool_calls: int
    servers: list[McpServerInfo]
    config_errors: list[str] = Field(default_factory=list)


class IntegrationsStatus(BaseModel):
    langsmith: LangSmithStatus
    mcp: McpStatus


class McpToolInfo(BaseModel):
    name: str
    description: str
    read_only: bool
    allowed: bool
    reason: str
    parameters: list[str] = Field(default_factory=list)


class McpServerTest(BaseModel):
    name: str
    ok: bool
    error: str | None = None
    tools: list[McpToolInfo] = Field(default_factory=list)


class McpTestResult(BaseModel):
    servers: list[McpServerTest]


class ConnectionTest(BaseModel):
    ok: bool
    message: str


class TraceInfo(BaseModel):
    enabled: bool
    project: str
    run_ids: list[str]
    urls: dict[str, str | None] = Field(default_factory=dict)
    note: str | None = None


class ToolCallOut(BaseModel):
    id: int
    created_at: Any
    agent: str
    server: str
    tool: str
    arguments: dict[str, Any]
    status: str
    result_preview: str
    duration_ms: int

    model_config = {"from_attributes": True}
