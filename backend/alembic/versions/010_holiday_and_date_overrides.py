"""add date_overrides table and holiday settings

Revision ID: 010_holiday_and_date_overrides
Revises: 009_add_middle_name_reading_mode
Create Date: 2026-03-31
"""
from alembic import op
import sqlalchemy as sa

revision = "010_holiday_and_date_overrides"
down_revision = "009_add_middle_name_reading_mode"
branch_labels = None
depends_on = None

HOLIDAY_SETTINGS = [
    ("holiday_mode", "closed"),
    ("holiday_start_time", "09:00"),
    ("holiday_end_time", "13:00"),
]


def upgrade() -> None:
    op.create_table(
        "date_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), unique=True, nullable=False, index=True),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("open_time", sa.String(5), nullable=True),
        sa.Column("close_time", sa.String(5), nullable=True),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 祝日設定を settings に挿入（既存キーがなければ）
    for key, value in HOLIDAY_SETTINGS:
        op.execute(
            sa.text(
                "INSERT INTO settings (key, value) VALUES (:key, :value) ON CONFLICT (key) DO NOTHING"
            ).bindparams(key=key, value=value)
        )


def downgrade() -> None:
    op.drop_table("date_overrides")

    for key, _ in HOLIDAY_SETTINGS:
        op.execute(
            sa.text("DELETE FROM settings WHERE key = :key").bindparams(key=key)
        )
