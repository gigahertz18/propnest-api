"""Small cross-service helpers with no natural home in a single service."""

from decimal import Decimal
from typing import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def integrity_error_message(exc: IntegrityError) -> str:
    """Return the DB driver's own error text from `exc`, falling back to
    the exception's string form. Services match domain-specific
    substrings (e.g. a constraint name) against this to translate a
    raw IntegrityError into a specific domain exception."""

    return str(exc.orig) if getattr(exc, "orig", None) is not None else str(exc)


def total_owed(record) -> Decimal:
    """Total amount owed on a billing record: amount_due plus any charged
    late fee. Single source of truth for both LeaseBillingService's
    apply_payment status determination and remaining_balance computation."""
    return record.amount_due + (record.late_fee_amount_charged or Decimal("0"))


async def attach_remaining_balance(db: AsyncSession, records: Sequence, payment_repo) -> None:
    """Populate a transient (non-persisted) `remaining_balance` on each
    billing record from non-voided payments linked via
    Payment.billing_record_id, in one bulk query regardless of how many
    records are passed. Floored at zero on overpayment — overpaid_amount is
    the dedicated credit field; this stays consistent with the dashboard's
    outstanding/credit being kept separate rather than netted (see
    BillingRecordRepository.sum_credits). Shared by LeaseBillingService's
    read/write paths and DashboardService.late_payments."""
    if not records:
        return
    ids = [r.id for r in records]
    paid_map = await payment_repo.sum_by_billing_record_ids(db, ids)
    for record in records:
        remaining = total_owed(record) - paid_map.get(record.id, Decimal("0"))
        record.remaining_balance = remaining if remaining > 0 else Decimal("0")
