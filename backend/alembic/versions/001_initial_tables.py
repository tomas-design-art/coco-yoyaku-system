"""initial tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-03-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # btree_gist拡張
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # practitioners
    op.create_table(
        'practitioners',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default='施術者'),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('display_order', sa.Integer(), server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # patients
    op.create_table(
        'patients',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('patient_number', sa.String(50), unique=True, nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('email', sa.String(200), nullable=True),
        sa.Column('line_id', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # menus
    op.create_table(
        'menus',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('price', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('display_order', sa.Integer(), server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # settings
    op.create_table(
        'settings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('key', sa.String(100), unique=True, nullable=False),
        sa.Column('value', sa.String(500), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # reservations
    op.create_table(
        'reservations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=True),
        sa.Column('practitioner_id', sa.Integer(), sa.ForeignKey('practitioners.id'), nullable=False),
        sa.Column('menu_id', sa.Integer(), sa.ForeignKey('menus.id'), nullable=True),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('channel', sa.String(20), nullable=False),
        sa.Column('source_ref', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('conflict_note', sa.Text(), nullable=True),
        sa.Column('hotpepper_synced', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('hold_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # EXCLUDE制約（二重予約防止の要）
    op.execute("""
        ALTER TABLE reservations ADD CONSTRAINT no_overlap
        EXCLUDE USING gist (
            practitioner_id WITH =,
            tstzrange(start_time, end_time) WITH &&
        )
        WHERE (status IN ('CONFIRMED', 'HOLD', 'PENDING'))
    """)

    # notification_log
    op.create_table(
        'notification_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reservation_id', sa.Integer(), sa.ForeignKey('reservations.id'), nullable=True),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_read', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # インデックス
    op.create_index('ix_reservations_practitioner_time', 'reservations', ['practitioner_id', 'start_time', 'end_time'])
    op.create_index('ix_reservations_status', 'reservations', ['status'])
    op.create_index('ix_reservations_start_time', 'reservations', ['start_time'])
    op.create_index('ix_notification_log_is_read', 'notification_log', ['is_read'])


def downgrade() -> None:
    op.drop_table('notification_log')
    op.drop_table('reservations')
    op.drop_table('settings')
    op.drop_table('menus')
    op.drop_table('patients')
    op.drop_table('practitioners')
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
