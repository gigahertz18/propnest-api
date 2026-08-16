"""link_payment_to_billing_record

Revision ID: a3f7c92e1b6d
Revises: f8d16c31acef
Create Date: 2026-08-17 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a3f7c92e1b6d"
down_revision: Union[str, None] = "f8d16c31acef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("billing_record_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_payments_billing_record_id"), "payments", ["billing_record_id"], unique=False)
    op.create_foreign_key(
        "payments_billing_record_id_fkey", "payments", "billing_records", ["billing_record_id"], ["id"]
    )

    op.add_column("billing_records", sa.Column("overpaid_amount", sa.Numeric(12, 2), nullable=True))
    op.create_check_constraint(
        "ck_billing_record_overpaid_amount_positive",
        "billing_records",
        "overpaid_amount IS NULL OR overpaid_amount > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_billing_record_overpaid_amount_positive", "billing_records", type_="check")
    op.drop_column("billing_records", "overpaid_amount")

    op.drop_constraint("payments_billing_record_id_fkey", "payments", type_="foreignkey")
    op.drop_index(op.f("ix_payments_billing_record_id"), table_name="payments")
    op.drop_column("payments", "billing_record_id")
