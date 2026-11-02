"""Replace the removed Ollama provider in saved user settings with Anthropic Claude.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    settings = sa.table(
        "user_settings",
        sa.column("llm_provider", sa.String()),
        sa.column("llm_model", sa.String()),
    )
    op.execute(
        settings.update()
        .where(settings.c.llm_provider == "ollama")
        .values(llm_provider="anthropic", llm_model="claude-sonnet-5-5")
    )


def downgrade() -> None:
    # Ollama is no longer supported, so there is nothing to restore.
    pass
