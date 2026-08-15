"""extend_payment_reference_check_void

Revision ID: 1e9348aa4d61
Revises: e946b8cb5e39
Create Date: 2026-08-14 08:17:04.135629

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.constraints import sql_in_clause

# revision identifiers, used by Alembic.
revision: str = "1e9348aa4d61"
down_revision: Union[str, None] = "e946b8cb5e39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_PAYMENT_METHODS = ("cash", "bank transfer", "gcash", "maya")
NEW_PAYMENT_METHODS = ("cash", "bank transfer", "gcash", "maya", "check")


def upgrade() -> None:
    op.add_column("payments", sa.Column("reference_number", sa.String(length=100), nullable=True))
    op.add_column("payments", sa.Column("corrects_payment_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("payments_corrects_payment_id_fkey", "payments", "payments", ["corrects_payment_id"], ["id"])

    # ALTER TYPE ... ADD VALUE can't run inside the transaction Alembic
    # normally wraps migrations in - autocommit blocks around just this
    # statement.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE payment_status_enum ADD VALUE IF NOT EXISTS 'VOIDED'")

    op.drop_constraint("ck_payment_method", "payments", type_="check")
    op.create_check_constraint(
        "ck_payment_method",
        "payments",
        sql_in_clause("payment_method", NEW_PAYMENT_METHODS),
    )


def downgrade() -> None:
    # Existing "check"-method rows would violate the narrower constraint -
    # this is an expected, deliberate failure on downgrade rather than a
    # silent data loss; the operator must resolve those rows first.
    op.drop_constraint("ck_payment_method", "payments", type_="check")
    op.create_check_constraint(
        "ck_payment_method",
        "payments",
        sql_in_clause("payment_method", OLD_PAYMENT_METHODS),
    )

    # Postgres doesn't support removing an enum value - would require
    # rebuilding the type. Left as-is: an unused 'VOIDED' member of
    # payment_status_enum after downgrade is harmless.

    op.drop_constraint("payments_corrects_payment_id_fkey", "payments", type_="foreignkey")
    op.drop_column("payments", "corrects_payment_id")
    op.drop_column("payments", "reference_number")
