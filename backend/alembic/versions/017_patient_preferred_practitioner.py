"""add preferred_practitioner_id to patients

Revision ID: 017_patient_preferred_practitioner
Revises: 016_shadow_logs
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa


revision = "017_pref_practitioner"
down_revision = "016_shadow_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column(
            "preferred_practitioner_id",
            sa.Integer(),
            sa.ForeignKey("practitioners.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("patients", "preferred_practitioner_id")
