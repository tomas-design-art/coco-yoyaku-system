"""extend name column lengths to 100 chars for foreign names

Revision ID: 008_extend_name_length
Revises: 007_patient_name_split
Create Date: 2026-03-31
"""
from alembic import op
import sqlalchemy as sa

revision = "008_extend_name_length"
down_revision = "007_patient_name_split"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("patients", "name", type_=sa.String(200), existing_nullable=False)
    op.alter_column("patients", "last_name", type_=sa.String(100), existing_nullable=True)
    op.alter_column("patients", "first_name", type_=sa.String(100), existing_nullable=True)
    op.alter_column("patients", "last_name_kana", type_=sa.String(100), existing_nullable=True)
    op.alter_column("patients", "first_name_kana", type_=sa.String(100), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("patients", "name", type_=sa.String(100), existing_nullable=False)
    op.alter_column("patients", "last_name", type_=sa.String(50), existing_nullable=True)
    op.alter_column("patients", "first_name", type_=sa.String(50), existing_nullable=True)
    op.alter_column("patients", "last_name_kana", type_=sa.String(50), existing_nullable=True)
    op.alter_column("patients", "first_name_kana", type_=sa.String(50), existing_nullable=True)
