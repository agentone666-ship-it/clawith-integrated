"""Add Feishu group delivery targets to schedules and triggers.

Background: The initial migration creates the current ORM metadata on empty databases.
Scope: Add nullable UUID delivery targets to historical schedule and trigger tables.
Idempotent: Accept the same columns already created by the initial migration;
reject incompatible existing columns before issuing DDL.

Revision ID: f065_feishu_group_target
Revises: f064_tool_call_tenants
Create Date: 2026-08-18 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.interfaces import ReflectedColumn

from alembic import op

revision: str = "f065_feishu_group_target"
down_revision: str | Sequence[str] | None = "f064_tool_call_tenants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("agent_schedules", "agent_triggers")
COLUMN = "delivery_target_id"


def _target_columns() -> dict[str, ReflectedColumn | None]:
    inspector = sa.inspect(op.get_bind())
    return {
        table: next(
            (column for column in inspector.get_columns(table) if column["name"] == COLUMN),
            None,
        )
        for table in TABLES
    }


def upgrade() -> None:
    columns = _target_columns()
    for table, column in columns.items():
        if column is not None and (
            not isinstance(column["type"], sa.Uuid) or not column["nullable"]
        ):
            raise RuntimeError(f"Expected nullable UUID {table}.{COLUMN}; refusing incompatible schema")
    for table, column in columns.items():
        if column is None:
            op.add_column(table, sa.Column(COLUMN, postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    columns = _target_columns()
    for table in reversed(TABLES):
        if columns[table] is not None:
            op.drop_column(table, COLUMN)
