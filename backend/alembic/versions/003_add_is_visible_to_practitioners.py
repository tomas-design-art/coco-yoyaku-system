"""add is_visible to practitioners

Revision ID: 003_add_is_visible
Revises: 002_patch_001_002
"""
from alembic import op
import sqlalchemy as sa

revision = "003_add_is_visible"
down_revision = "002_patch_001_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "practitioners",
        sa.Column("is_visible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("practitioners", "is_visible")
