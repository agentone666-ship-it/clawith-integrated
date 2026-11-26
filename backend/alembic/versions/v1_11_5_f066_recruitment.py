"""Add HR recruitment dossiers.

Background: Persist conversation, editable resume and human interview feedback.
Scope: One tenant/owner-scoped table; native Agents and Runs remain authoritative.
Idempotent: Table creation is guarded; downgrade removes only this feature table.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f066_recruitment"
down_revision = "f065_feishu_group_target"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("recruitments"):
        return
    op.create_table(
        "recruitments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("messages", postgresql.JSONB(), nullable=False),
        sa.Column("resume", postgresql.JSONB(), nullable=True),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("candidate_hash", sa.String(64), nullable=True),
        sa.Column("interviews", postgresql.JSONB(), nullable=False),
        sa.Column("hired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_recruitments_owner_updated", "recruitments", ["tenant_id", "owner_id", "updated_at"])


def downgrade():
    op.drop_index("ix_recruitments_owner_updated", table_name="recruitments")
    op.drop_table("recruitments")
