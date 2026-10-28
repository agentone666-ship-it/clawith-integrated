"""Background: Python releases pin a verified test and its compiler identity.
Scope: additive, nullable columns only in desktop_automation. Idempotent on fresh
installs whose initial metadata already includes these columns; no data backfill.
"""

import sqlalchemy as sa

from alembic import op

revision = "002_script_publication_proof"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("versions", schema="desktop_automation")}
    if "validation_run_id" not in columns:
        op.add_column("versions", sa.Column("validation_run_id", sa.Uuid(), nullable=True), schema="desktop_automation")
        op.create_foreign_key(
            "fk_automation_version_validation",
            "versions",
            "playbacks",
            ["validation_run_id"],
            ["id"],
            source_schema="desktop_automation",
            referent_schema="desktop_automation",
        )
    if "compiler_fingerprint" not in columns:
        op.add_column(
            "versions", sa.Column("compiler_fingerprint", sa.String(64), nullable=True), schema="desktop_automation"
        )


def downgrade():
    op.drop_constraint("fk_automation_version_validation", "versions", schema="desktop_automation", type_="foreignkey")
    op.drop_column("versions", "compiler_fingerprint", schema="desktop_automation")
    op.drop_column("versions", "validation_run_id", schema="desktop_automation")
