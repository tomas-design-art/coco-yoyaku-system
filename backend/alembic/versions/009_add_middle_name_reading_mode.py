"""add registration_mode, middle_name, reading to patients

Revision ID: 009_add_middle_name_reading_mode
Revises: 008_extend_name_length
Create Date: 2026-03-31
"""
from alembic import op
import sqlalchemy as sa

revision = "009_add_middle_name_reading_mode"
down_revision = "008_extend_name_length"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("registration_mode", sa.String(20), nullable=False, server_default="split"))
    op.add_column("patients", sa.Column("middle_name", sa.String(100), nullable=True))
    op.add_column("patients", sa.Column("reading", sa.String(200), nullable=True))

    # 既存データ: last_name_kana + first_name_kana → reading へコピー
    op.execute("""
        UPDATE patients
        SET reading = TRIM(COALESCE(last_name_kana, '') || ' ' || COALESCE(first_name_kana, ''))
        WHERE last_name_kana IS NOT NULL OR first_name_kana IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column("patients", "reading")
    op.drop_column("patients", "middle_name")
    op.drop_column("patients", "registration_mode")
