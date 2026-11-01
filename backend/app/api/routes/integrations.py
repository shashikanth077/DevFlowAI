"""Status and diagnostics for external integrations: LangSmith observability and MCP tool servers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.database.session import get_db
from app.mcp_tools.broker import McpToolBroker
from app.mcp_tools.config import resolve_specs
from app.mcp_tools.connection import McpError
from app.models import User
from app.observability.tracing import get_tracing
from app.schemas.integrations import (
    ConnectionTest,
    IntegrationsStatus,
    LangSmithStatus,
    McpServerInfo,
    McpServerTest,
    McpStatus,
    McpTestResult,
    McpToolInfo,
)
from app.services.settings_service import get_or_create_settings

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class _NullRecorder:
    def log(self, *_a, **_k) -> None: ...
    def save_tool_call(self, *_a, **_k) -> None: ...


@router.get("/status", response_model=IntegrationsStatus)
def integrations_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    settings = get_settings()
    prefs = get_or_create_settings(db, user.id)
    db.commit()
    disabled = set(prefs.mcp_disabled_servers or [])
    specs, errors = resolve_specs(settings, Path("."))
    return IntegrationsStatus(
        langsmith=LangSmithStatus(**get_tracing().status()),
        mcp=McpStatus(
            available=settings.mcp_enabled, enabled_for_user=prefs.mcp_enabled,
            max_tool_calls=settings.mcp_max_tool_calls, config_errors=errors,
            servers=[McpServerInfo(**s.public(), enabled_for_user=s.name not in disabled) for s in specs],
        ),
    )


@router.post("/langsmith/test", response_model=ConnectionTest)
def test_langsmith(_: User = Depends(get_current_user)):
    return ConnectionTest(**get_tracing().check_connection())


@router.post("/mcp/test", response_model=McpTestResult)
def test_mcp(_: User = Depends(get_current_user)):
    """Connect to every configured MCP server and report its tools and how policy classifies them."""
    settings = get_settings()
    results: list[McpServerTest] = []
    with tempfile.TemporaryDirectory(prefix="devflow-mcp-probe-") as probe_dir:
        specs, _ = resolve_specs(settings, Path(probe_dir))
        broker = McpToolBroker(specs, settings, _NullRecorder())
        try:
            for spec in specs:
                try:
                    tools = broker.discover(spec)
                except McpError as exc:
                    results.append(McpServerTest(name=spec.name, ok=False, error=exc.message))
                    continue
                results.append(McpServerTest(name=spec.name, ok=True, tools=[
                    McpToolInfo(
                        name=t.name, description=(t.description or "").splitlines()[0][:200] if t.description else "",
                        read_only=t.read_only, allowed=t.allowed, reason=t.reason,
                        parameters=list((t.input_schema or {}).get("properties", {})),
                    ) for t in tools
                ]))
        finally:
            broker.close()
    return McpTestResult(servers=results)
