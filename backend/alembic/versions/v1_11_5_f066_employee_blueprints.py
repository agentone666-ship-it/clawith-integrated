"""Add user-owned employee job drafts.

Background: Business users need persistent, reviewable job configurations.
Scope: One product table; existing Agent Runtime state is unchanged.
Idempotent: Table and index creation are guarded; downgrade removes only this table.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f066_employee_blueprints"
down_revision = "f065_feishu_group_target"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_blueprints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requirement", sa.Text(), nullable=False),
        sa.Column("specification", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "published_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=True,
            unique=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        "ix_employee_blueprints_owner_updated",
        "employee_blueprints",
        ["tenant_id", "created_by", "updated_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("employee_blueprints", if_exists=True)
