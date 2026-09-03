"""add patient line_id lookup index

Revision ID: 027_patient_line_id_index
Revises: 026_line_webhook_events
Create Date: 2026-09-04
"""

from alembic import op


revision = "027_patient_line_id_index"
down_revision = "026_line_webhook_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_patients_line_id",
        "patients",
        ["line_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_patients_line_id", table_name="patients")