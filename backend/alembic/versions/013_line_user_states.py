"""add line_user_states table

Revision ID: 013_line_user_states
Revises: 012_patient_defaults
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "013_line_user_states"
down_revision = "012_patient_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "line_user_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("line_user_id", sa.String(length=100), nullable=False),
        sa.Column("current_step", sa.String(length=50), nullable=False, server_default="idle"),
        sa.Column("context_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_line_user_states_line_user_id", "line_user_states", ["line_user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_line_user_states_line_user_id", table_name="line_user_states")
    op.drop_table("line_user_states")
