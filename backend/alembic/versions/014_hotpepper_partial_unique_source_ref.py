"""add partial unique index for hotpepper source_ref

Revision ID: 014_hotpepper_partial_unique_source_ref
Revises: 013_line_user_states
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa


revision = '014_hotpepper_unique'
down_revision = "013_line_user_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_reservations_hotpepper_source_ref",
        "reservations",
        ["source_ref"],
        unique=True,
        postgresql_where=sa.text("channel = 'HOTPEPPER' AND source_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_reservations_hotpepper_source_ref", table_name="reservations")
