"""add practitioner_schedules and schedule_overrides

Revision ID: 006
Revises: 005_add_color_id_to_menus
"""
from alembic import op
import sqlalchemy as sa

revision = "006_practitioner_schedules"
down_revision = "005_add_color_id_to_menus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practitioner_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("practitioner_id", sa.Integer(), sa.ForeignKey("practitioners.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("is_working", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("start_time", sa.String(5), nullable=False, server_default="09:00"),
        sa.Column("end_time", sa.String(5), nullable=False, server_default="20:00"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("practitioner_id", "day_of_week", name="uq_practitioner_day"),
    )

    op.create_table(
        "schedule_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("practitioner_id", sa.Integer(), sa.ForeignKey("practitioners.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("is_working", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("practitioner_id", "date", name="uq_practitioner_date"),
    )


def downgrade() -> None:
    op.drop_table("schedule_overrides")
    op.drop_table("practitioner_schedules")
