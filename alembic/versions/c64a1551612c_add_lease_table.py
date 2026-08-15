"""add_lease_table

Revision ID: c64a1551612c
Revises: 7916842c18d3
Create Date: 2026-08-15 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c64a1551612c"
down_revision: Union[str, None] = "7916842c18d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("monthly_rent", sa.Numeric(12, 2), nullable=False),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column(
            "billing_cycle",
            sa.Enum("monthly", name="lease_billing_cycle_enum"),
            nullable=False,
            server_default="monthly",
        ),
        sa.Column("security_deposit", sa.Numeric(12, 2), nullable=True),
        sa.Column("advance_payment", sa.Numeric(12, 2), nullable=True),
        sa.Column("late_fee_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("late_fee_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("grace_period_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "renewal_option",
            sa.Enum("auto", "manual", "none", name="lease_renewal_option_enum"),
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "ENDED", name="lease_status_enum"),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id", name="uq_lease_contract_id"),
        sa.CheckConstraint("monthly_rent > 0", name="ck_lease_monthly_rent_positive"),
        sa.CheckConstraint("due_day >= 1 AND due_day <= 31", name="ck_lease_due_day_range"),
        sa.CheckConstraint(
            "security_deposit IS NULL OR security_deposit > 0", name="ck_lease_security_deposit_positive"
        ),
        sa.CheckConstraint("advance_payment IS NULL OR advance_payment > 0", name="ck_lease_advance_payment_positive"),
        sa.CheckConstraint("grace_period_days >= 0", name="ck_lease_grace_period_days_nonnegative"),
        sa.CheckConstraint(
            "(late_fee_amount IS NULL) <> (late_fee_percent IS NULL)", name="ck_lease_late_fee_exactly_one"
        ),
        sa.CheckConstraint("late_fee_amount IS NULL OR late_fee_amount > 0", name="ck_lease_late_fee_amount_positive"),
        sa.CheckConstraint(
            "late_fee_percent IS NULL OR (late_fee_percent > 0 AND late_fee_percent <= 100)",
            name="ck_lease_late_fee_percent_range",
        ),
        sa.CheckConstraint("end_date IS NULL OR end_date > start_date", name="ck_lease_dates"),
    )
    op.create_index(op.f("ix_leases_contract_id"), "leases", ["contract_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_leases_contract_id"), table_name="leases")
    op.drop_table("leases")
    sa.Enum(name="lease_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="lease_renewal_option_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="lease_billing_cycle_enum").drop(op.get_bind(), checkfirst=True)
