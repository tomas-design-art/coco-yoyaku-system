"""add shadow_logs table

Revision ID: 016_shadow_logs
Revises: 015_menu_variable_duration
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "016_shadow_logs"
down_revision = "015_menu_variable_duration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("line_user_id", sa.String(100), nullable=False, index=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("has_reservation_intent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("analysis_result", JSONB, nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("shadow_logs")
