"""reservation_series table + reservations.series_id

Revision ID: 019
Revises: 018
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reservation_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=True),
        sa.Column("practitioner_id", sa.Integer(), sa.ForeignKey("practitioners.id"), nullable=False),
        sa.Column("menu_id", sa.Integer(), sa.ForeignKey("menus.id"), nullable=True),
        sa.Column("color_id", sa.Integer(), sa.ForeignKey("reservation_colors.id"), nullable=True),
        sa.Column("start_time", sa.String(5), nullable=False, comment="HH:MM"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False, comment="weekly/biweekly/monthly"),
        sa.Column("channel", sa.String(20), nullable=False, server_default="PHONE"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("remaining_count", sa.Integer(), nullable=False, comment="残り予約回数"),
        sa.Column("total_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True, comment="延長通知を最後に出した日時"),
        sa.Column("is_active", sa.Boolean(), server_default="true", comment="延長終了=false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column(
        "reservations",
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("reservation_series.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reservations", "series_id")
    op.drop_table("reservation_series")
