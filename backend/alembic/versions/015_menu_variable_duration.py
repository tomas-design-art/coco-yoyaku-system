"""add variable duration fields to menus

Revision ID: 015_menu_variable_duration
Revises: 014_hotpepper_unique
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa


revision = "015_menu_variable_duration"
down_revision = "014_hotpepper_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menus",
        sa.Column("is_duration_variable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "menus",
        sa.Column("max_duration_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("menus", "max_duration_minutes")
    op.drop_column("menus", "is_duration_variable")
