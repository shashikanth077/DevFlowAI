"""LangGraph checkpointer selection.

Checkpoints are written after every super-step, keyed by ``thread_id`` =
workflow id. If the API process stops mid-run, the workflow is resumed from
its last checkpoint on startup (see ``workflow_service.resume_interrupted``).
"""

from __future__ import annotations

import logging
import sqlite3
import threading

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_checkpointer: BaseCheckpointSaver | None = None
_resources: list = []


def get_checkpointer(settings: Settings | None = None) -> BaseCheckpointSaver:
    global _checkpointer
    with _lock:
        if _checkpointer is not None:
            return _checkpointer
        settings = settings or get_settings()
        backend = settings.resolved_checkpoint_backend()
        if backend == "postgres":
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(
                settings.checkpoint_postgres_dsn, max_size=10, open=True,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            )
            saver = PostgresSaver(pool)
            saver.setup()
            _resources.append(pool)
        elif backend == "sqlite":
            from langgraph.checkpoint.sqlite import SqliteSaver

            conn = sqlite3.connect(settings.checkpoint_sqlite_path, check_same_thread=False)
            saver = SqliteSaver(conn)
            saver.setup()
            _resources.append(conn)
        else:
            saver = InMemorySaver()
        logger.info("Checkpointer initialised", extra={"backend": backend})
        _checkpointer = saver
        return saver


def set_checkpointer(saver: BaseCheckpointSaver | None) -> None:
    global _checkpointer
    with _lock:
        _checkpointer = saver


def close_checkpointer() -> None:
    global _checkpointer
    with _lock:
        for resource in _resources:
            try:
                resource.close()
            except Exception:  # noqa: BLE001
                logger.warning("Failed to close checkpointer resource", exc_info=True)
        _resources.clear()
        _checkpointer = None
