"""add color_id to menus

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa

revision = "005_add_color_id_to_menus"
down_revision = "004_weekly_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menus",
        sa.Column("color_id", sa.Integer(), sa.ForeignKey("reservation_colors.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("menus", "color_id")
