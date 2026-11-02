"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import auth, dashboard, github, integrations, projects, repositories, settings, workflows
from app.core.config import get_settings
from app.core.errors import DevFlowError
from app.core.logging import configure_logging
from app.database.connection import get_engine
from app.database.schema import schema_status
from app.observability.tracing import configure_tracing, get_tracing
from app.orchestration.checkpointing import close_checkpointer
from app.services.execution_service import DockerSandbox
from app.services.workflow_service import get_workflow_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    cfg = get_settings()
    configure_logging(cfg.log_level, cfg.log_json)
    Path(cfg.workspace_root).mkdir(parents=True, exist_ok=True)
    configure_tracing(cfg)
    schema = schema_status(get_engine())
    if not schema["ok"]:
        logger.error(schema["message"], extra={"schema_current": schema["current"], "schema_head": schema["head"]})
    manager = get_workflow_manager()
    if cfg.resume_workflows_on_startup and cfg.environment != "test":
        try:
            resumed = manager.resume_interrupted()
            if resumed:
                logger.info("Resumed interrupted workflows", extra={"workflow_ids": resumed})
        except Exception:  # noqa: BLE001 - startup must not crash because of one bad workflow
            logger.exception("Workflow recovery failed")
    yield
    manager.shutdown()
    get_tracing().flush()
    close_checkpointer()


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title=cfg.app_name, version="1.0.0", lifespan=lifespan,
                  description="Autonomous multi-agent software engineering platform")
    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(DevFlowError)
    async def devflow_error_handler(_: Request, exc: DevFlowError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "details": exc.details})

    for module in (auth, projects, repositories, github, workflows, settings, dashboard, integrations):
        app.include_router(module.router)

    @app.get("/health", tags=["health"])
    def health() -> dict:
        checks: dict[str, dict] = {}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            checks["database"] = {"ok": False, "error": str(exc)[:200]}
        sandbox_ok, sandbox_info = DockerSandbox(cfg).available()
        checks["sandbox"] = {"ok": sandbox_ok, "info": sandbox_info}
        if cfg.llm_provider == "ollama":
            try:
                response = httpx.get(f"{cfg.ollama_base_url.rstrip('/')}/api/version", timeout=2)
                checks["ollama"] = {"ok": response.status_code == 200, "version": response.json().get("version")}
            except Exception as exc:  # noqa: BLE001
                checks["ollama"] = {"ok": False, "error": str(exc)[:200]}
        checks["schema"] = schema_status(get_engine())
        status = "ok" if checks["database"]["ok"] and checks["schema"]["ok"] else "degraded"
        return {"status": status, "app": cfg.app_name, "checks": checks,
                "checkpointer": cfg.resolved_checkpoint_backend()}

    return app


app = create_app()
