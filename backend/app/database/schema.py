"""Check that the database schema matches the migrations this code expects."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def schema_status(engine: Engine) -> dict:
    """Return whether the database is at the newest migration (alembic head)."""
    script = ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))
    head = script.get_current_head()
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "current": None, "head": head, "message": f"Cannot read schema: {exc}"[:300]}
    if current == head:
        return {"ok": True, "current": current, "head": head, "message": "Database schema is up to date."}
    return {
        "ok": False, "current": current, "head": head,
        "message": f"Database schema is at revision {current or 'none'} but the code needs {head}. "
                   "Run: alembic upgrade head",
    }
