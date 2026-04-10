"""add menu_price_tiers table

Revision ID: 018_menu_price_tiers
Revises: 017_pref_practitioner
Create Date: 2026-04-11
"""
from alembic import op
import sqlalchemy as sa


revision = "018_menu_price_tiers"
down_revision = "017_pref_practitioner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "menu_price_tiers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("menu_id", sa.Integer(), sa.ForeignKey("menus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index("ix_menu_price_tiers_menu_id", "menu_price_tiers", ["menu_id"])


def downgrade() -> None:
    op.drop_index("ix_menu_price_tiers_menu_id", table_name="menu_price_tiers")
    op.drop_table("menu_price_tiers")
