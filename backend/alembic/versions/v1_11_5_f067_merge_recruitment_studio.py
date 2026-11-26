"""Merge HR recruitment and existing employee blueprint histories.

Background: Integrate independently developed HR and automation branches.
Scope: Merge the two Runtime migration heads without changing historical revisions.
Idempotent: No DDL or data changes; both product tables remain intact.
"""

revision = "f067_merge_recruitment_studio"
down_revision = ("f066_employee_blueprints", "f066_recruitment")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
