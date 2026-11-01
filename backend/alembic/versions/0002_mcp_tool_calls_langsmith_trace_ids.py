"""mcp tool calls, langsmith trace ids

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01 21:15:46.146223
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('tool_calls',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('workflow_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('agent', sa.String(length=60), nullable=False),
    sa.Column('server', sa.String(length=100), nullable=False),
    sa.Column('tool', sa.String(length=200), nullable=False),
    sa.Column('arguments', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('result_preview', sa.Text(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflow_executions.id'], name=op.f('fk_tool_calls_workflow_id_workflow_executions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_calls'))
    )
    op.create_index(op.f('ix_tool_calls_workflow_id'), 'tool_calls', ['workflow_id'], unique=False)
    op.add_column('user_settings', sa.Column('mcp_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('user_settings', sa.Column('mcp_disabled_servers', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))
    op.add_column('workflow_executions', sa.Column('trace_run_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))


def downgrade() -> None:
    op.drop_column('workflow_executions', 'trace_run_ids')
    op.drop_column('user_settings', 'mcp_disabled_servers')
    op.drop_column('user_settings', 'mcp_enabled')
    op.drop_index(op.f('ix_tool_calls_workflow_id'), table_name='tool_calls')
    op.drop_table('tool_calls')
