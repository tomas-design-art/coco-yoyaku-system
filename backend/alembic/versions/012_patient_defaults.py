"""add patient defaults and repeat reservation support

Revision ID: 012_patient_defaults
Revises: 011_unavailable_times
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa

revision = "012_patient_defaults"
down_revision = "011_unavailable_times"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("default_menu_id", sa.Integer(), sa.ForeignKey("menus.id", ondelete="SET NULL"), nullable=True))
    op.add_column("patients", sa.Column("default_duration", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("patients", "default_duration")
    op.drop_column("patients", "default_menu_id")
