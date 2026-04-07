"""add reservation_colors, color_id, chat_sessions

Revision ID: 002_patch_001_002
Revises: 001_initial
Create Date: 2026-03-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = '002_patch_001_002'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # reservation_colors テーブル
    op.create_table(
        'reservation_colors',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('color_code', sa.String(7), nullable=False),
        sa.Column('display_order', sa.Integer(), server_default=sa.text('0')),
        sa.Column('is_default', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # reservations に color_id カラムを追加
    op.add_column(
        'reservations',
        sa.Column('color_id', sa.Integer(), sa.ForeignKey('reservation_colors.id'), nullable=True),
    )

    # 初期データ: 予約色
    op.execute("""
        INSERT INTO reservation_colors (name, color_code, display_order, is_default) VALUES
        ('保険診療', '#3B82F6', 1, TRUE),
        ('自費診療', '#10B981', 2, FALSE),
        ('初診', '#F97316', 3, FALSE)
    """)

    # chat_sessions テーブル (PATCH_002)
    op.create_table(
        'chat_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('messages', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('reservation_id', sa.Integer(), sa.ForeignKey('reservations.id'), nullable=True),
        sa.Column('status', sa.String(20), server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('chat_sessions')
    op.drop_column('reservations', 'color_id')
    op.drop_table('reservation_colors')
