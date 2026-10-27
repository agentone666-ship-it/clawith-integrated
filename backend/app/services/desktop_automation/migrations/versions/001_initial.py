"""Background: desktop recording needs durable drafts, versions and receipts.
Scope: only desktop_automation schema. Idempotent: metadata emits missing tables;
no existing Clawith table, Runtime state or application data is migrated.
"""

from alembic import op
from app.services.desktop_automation.models import AutomationBase

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    AutomationBase.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    AutomationBase.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
