"""add weekly_schedules table

Revision ID: 004_weekly_schedules
Revises: 003_add_is_visible
"""
from alembic import op
import sqlalchemy as sa

revision = "004_weekly_schedules"
down_revision = "003_add_is_visible"
branch_labels = None
depends_on = None

# デフォルト: 月〜土は営業、日曜は休診
DEFAULT_SCHEDULES = [
    {"day_of_week": 0, "is_open": False, "open_time": "09:00", "close_time": "20:00"},  # 日
    {"day_of_week": 1, "is_open": True,  "open_time": "09:00", "close_time": "20:00"},  # 月
    {"day_of_week": 2, "is_open": True,  "open_time": "09:00", "close_time": "20:00"},  # 火
    {"day_of_week": 3, "is_open": True,  "open_time": "09:00", "close_time": "20:00"},  # 水
    {"day_of_week": 4, "is_open": True,  "open_time": "09:00", "close_time": "20:00"},  # 木
    {"day_of_week": 5, "is_open": True,  "open_time": "09:00", "close_time": "20:00"},  # 金
    {"day_of_week": 6, "is_open": True,  "open_time": "09:00", "close_time": "20:00"},  # 土
]


def upgrade() -> None:
    table = op.create_table(
        "weekly_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day_of_week", sa.Integer(), unique=True, nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("open_time", sa.String(5), nullable=False, server_default="09:00"),
        sa.Column("close_time", sa.String(5), nullable=False, server_default="20:00"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.bulk_insert(table, DEFAULT_SCHEDULES)


def downgrade() -> None:
    op.drop_table("weekly_schedules")
