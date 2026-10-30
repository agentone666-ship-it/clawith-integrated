"""Background: authoring trials use the originating Agent's persistent desktop.
Scope: additive nullable workflow association in the capability schema only.
Idempotent: fresh installs may already contain the metadata-defined column.
"""

import sqlalchemy as sa

from alembic import op

revision = "003_desktop_agent"
down_revision = "002_script_publication_proof"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("workflows", schema="desktop_automation")}
    if "desktop_agent_id" not in columns:
        op.add_column("workflows", sa.Column("desktop_agent_id", sa.Uuid(), nullable=True), schema="desktop_automation")


def downgrade():
    op.drop_column("workflows", "desktop_agent_id", schema="desktop_automation")
