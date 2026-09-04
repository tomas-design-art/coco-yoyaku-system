"""add partial unique index for LINE reservation source_ref

Revision ID: 028_line_reservation_source_ref
Revises: 027_patient_line_id_index
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa


revision = "028_line_reservation_source_ref"
down_revision = "027_patient_line_id_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_reservations_line_source_ref",
        "reservations",
        ["source_ref"],
        unique=True,
        postgresql_where=sa.text("channel = 'LINE' AND source_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_reservations_line_source_ref", table_name="reservations")