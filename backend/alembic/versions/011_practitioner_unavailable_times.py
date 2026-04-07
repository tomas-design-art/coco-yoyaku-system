"""add practitioner_unavailable_times table

Revision ID: 011_practitioner_unavailable_times
Revises: 010_holiday_and_date_overrides
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa

revision = "011_unavailable_times"
down_revision = "010_holiday_and_date_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practitioner_unavailable_times",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("practitioner_id", sa.Integer(), sa.ForeignKey("practitioners.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("end_time", sa.String(5), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("practitioner_unavailable_times")
