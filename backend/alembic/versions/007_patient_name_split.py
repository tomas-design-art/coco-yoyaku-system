"""split patient name into last_name/first_name, add kana/birth_date/is_active

Revision ID: 007
Revises: 006_practitioner_schedules
"""
from alembic import op
import sqlalchemy as sa

revision = "007_patient_name_split"
down_revision = "006_practitioner_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("last_name", sa.String(50), nullable=True))
    op.add_column("patients", sa.Column("first_name", sa.String(50), nullable=True))
    op.add_column("patients", sa.Column("last_name_kana", sa.String(50), nullable=True))
    op.add_column("patients", sa.Column("first_name_kana", sa.String(50), nullable=True))
    op.add_column("patients", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column(
        "patients",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # 既存データの name を last_name / first_name に分割
    # name が "姓 名" 形式の場合、スペースで分割
    op.execute("""
        UPDATE patients
        SET last_name = SPLIT_PART(TRIM(name), ' ', 1),
            first_name = CASE
                WHEN POSITION(' ' IN TRIM(name)) > 0
                THEN SUBSTRING(TRIM(name) FROM POSITION(' ' IN TRIM(name)) + 1)
                ELSE ''
            END
        WHERE last_name IS NULL
    """)

    # patient_number が未設定の既存データに自動採番
    op.execute("""
        WITH max_num AS (
            SELECT COALESCE(
                MAX(CAST(SUBSTRING(patient_number FROM 2) AS INTEGER)), 0
            ) AS val
            FROM patients
            WHERE patient_number ~ '^P[0-9]+$'
        ),
        numbered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn
            FROM patients
            WHERE patient_number IS NULL
        )
        UPDATE patients
        SET patient_number = 'P' || LPAD(CAST(max_num.val + numbered.rn AS TEXT), 6, '0')
        FROM numbered, max_num
        WHERE patients.id = numbered.id
    """)


def downgrade() -> None:
    op.drop_column("patients", "is_active")
    op.drop_column("patients", "birth_date")
    op.drop_column("patients", "first_name_kana")
    op.drop_column("patients", "last_name_kana")
    op.drop_column("patients", "first_name")
    op.drop_column("patients", "last_name")
