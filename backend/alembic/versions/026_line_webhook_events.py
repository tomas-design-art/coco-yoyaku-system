"""add line_webhook_events inbox table

Revision ID: 026_line_webhook_events
Revises: 025_line_autopilot_patients
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "026_line_webhook_events"
down_revision = "025_line_autopilot_patients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "line_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("line_user_id", sa.String(length=100), nullable=True),
        sa.Column("event_timestamp", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_redelivery",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_line_webhook_events_event_id",
        "line_webhook_events",
        ["event_id"],
        unique=True,
    )
    op.create_index(
        "ix_line_webhook_events_status",
        "line_webhook_events",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_line_webhook_events_line_user_id",
        "line_webhook_events",
        ["line_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_line_webhook_events_line_user_id", table_name="line_webhook_events")
    op.drop_index("ix_line_webhook_events_status", table_name="line_webhook_events")
    op.drop_index("ix_line_webhook_events_event_id", table_name="line_webhook_events")
    op.drop_table("line_webhook_events")
