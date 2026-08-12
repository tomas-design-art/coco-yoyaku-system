"""add line autopilot patient flag

Revision ID: 025_line_autopilot_patients
Revises: 024_rpa_call_logs
"""

from alembic import op
import sqlalchemy as sa


revision = "025_line_autopilot_patients"
down_revision = "024_rpa_call_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column(
            "line_autopilot_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("patients", "line_autopilot_enabled")