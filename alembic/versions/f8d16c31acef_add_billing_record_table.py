"""add_billing_record_table

Revision ID: f8d16c31acef
Revises: c64a1551612c
Create Date: 2026-08-16 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f8d16c31acef"
down_revision: Union[str, None] = "c64a1551612c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount_due", sa.Numeric(12, 2), nullable=False),
        sa.Column("late_fee_applied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("late_fee_amount_charged", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "partially_paid",
                "paid",
                "overdue",
                "written_off",
                name="billing_record_status_enum",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lease_id"], ["leases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lease_id", "period_start", name="uq_billing_record_lease_id_period_start"),
        sa.CheckConstraint("amount_due > 0", name="ck_billing_record_amount_due_positive"),
        sa.CheckConstraint(
            "late_fee_amount_charged IS NULL OR late_fee_amount_charged > 0",
            name="ck_billing_record_late_fee_amount_positive",
        ),
        sa.CheckConstraint(
            "(late_fee_applied = false AND late_fee_amount_charged IS NULL) "
            "OR (late_fee_applied = true AND late_fee_amount_charged IS NOT NULL)",
            name="ck_billing_record_late_fee_consistency",
        ),
        sa.CheckConstraint("period_end > period_start", name="ck_billing_record_period_dates"),
        sa.CheckConstraint("due_date >= period_start", name="ck_billing_record_due_date_after_period_start"),
    )
    op.create_index(op.f("ix_billing_records_lease_id"), "billing_records", ["lease_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_billing_records_lease_id"), table_name="billing_records")
    op.drop_table("billing_records")
    sa.Enum(name="billing_record_status_enum").drop(op.get_bind(), checkfirst=True)
