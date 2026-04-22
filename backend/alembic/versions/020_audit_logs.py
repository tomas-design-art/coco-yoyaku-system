"""add audit_logs table

Revision ID: 020_audit_logs
Revises: 019_reservation_series
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "020_audit_logs"
down_revision = "019_reservation_series"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='audit_logs')"
        )
    )
    table_exists = result.scalar()

    if not table_exists:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("operator", sa.String(length=100), nullable=False),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column("target_id", sa.Integer(), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
        )
        op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")
    op.drop_table("audit_logs")
