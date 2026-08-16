from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.billing_record import BillingRecord, BillingRecordStatus, last_day_of_month
from app.repositories.billing_record import BillingRecordRepository
from app.repositories.contract import ContractRepository
from app.repositories.lease import LeaseRepository
from app.schemas.billing_record import BillingRecordCreate
from app.services.audit import write_audit_log
from app.services.base import ResourceAuthorizationMixin
from app.services.utils import integrity_error_message
from app.services.exceptions import (
    BillingRecordAlreadyGeneratedError,
    BillingRecordForbiddenError,
    InvalidBillingRecordTransitionError,
    RelatedResourceNotFoundError,
)


class LeaseBillingService(ResourceAuthorizationMixin):
    """
    Business logic for `BillingRecord` generation and status lifecycle —
    long-term-lease-specific, mirroring `LeaseService`. No cron/scheduling:
    generation and overdue-evaluation are both explicit, manually-triggered
    operations (see recurring-billing-engine's scope).
    """

    forbidden_error = BillingRecordForbiddenError

    _VALID_TRANSITIONS: dict[BillingRecordStatus, set[BillingRecordStatus]] = {
        BillingRecordStatus.pending: {
            BillingRecordStatus.overdue,
            BillingRecordStatus.partially_paid,
            BillingRecordStatus.paid,
        },
        BillingRecordStatus.partially_paid: {
            BillingRecordStatus.paid,
            BillingRecordStatus.overdue,
            BillingRecordStatus.written_off,
        },
        BillingRecordStatus.overdue: {
            BillingRecordStatus.partially_paid,
            BillingRecordStatus.paid,
            BillingRecordStatus.written_off,
        },
        BillingRecordStatus.paid: set(),
        BillingRecordStatus.written_off: set(),
    }

    def __init__(
        self,
        billing_record_repo: BillingRecordRepository,
        lease_repo: LeaseRepository,
        contract_repo: ContractRepository | None = None,
        property_repo=None,
    ) -> None:
        self.billing_record_repo = billing_record_repo
        self.lease_repo = lease_repo
        self.contract_repo = contract_repo
        self.property_repo = property_repo

    def _transition(self, record: BillingRecord, new_status: BillingRecordStatus) -> None:
        allowed = self._VALID_TRANSITIONS.get(record.status, set())
        if new_status not in allowed:
            raise InvalidBillingRecordTransitionError(
                f"Cannot transition BillingRecord {record.id} from {record.status} to {new_status}."
            )
        record.status = new_status

    async def generate_billing_record(
        self,
        db: AsyncSession,
        lease_id: UUID,
        period_start: date,
        current_user,
    ) -> BillingRecord:
        """
        Relies on a DB constraint (not a pre-check) to prevent two concurrent
        requests both generating a BillingRecord for the same lease+period;
        a resulting IntegrityError is translated into
        `BillingRecordAlreadyGeneratedError`.
        """
        lease = await self.lease_repo.get_by_id(db, lease_id)
        if not lease:
            raise RelatedResourceNotFoundError(f"Lease {lease_id} not found.")

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=lease.contract_id,
        )

        period_end = last_day_of_month(period_start)
        due_date = date(period_start.year, period_start.month, min(lease.due_day, period_end.day))

        payload = BillingRecordCreate(
            lease_id=lease_id,
            period_start=period_start,
            period_end=period_end,
            due_date=due_date,
            amount_due=lease.monthly_rent,
            status=BillingRecordStatus.pending,
        )

        try:
            record = await self.billing_record_repo.create(db, payload)
        except IntegrityError as e:
            self._raise_if_already_generated_conflict(e)
            raise

        write_audit_log(db, current_user, AuditAction.CREATE, "BillingRecord", record.id)
        await db.commit()
        return record

    async def evaluate_overdue(
        self,
        db: AsyncSession,
        billing_record_id: UUID,
        current_user,
        as_of: date | None = None,
    ) -> BillingRecord:
        record = await self.billing_record_repo.get_by_id(db, billing_record_id)
        if not record:
            raise RelatedResourceNotFoundError(f"BillingRecord {billing_record_id} not found.")

        lease = await self.lease_repo.get_by_id(db, record.lease_id)
        if not lease:
            raise RelatedResourceNotFoundError(f"Lease {record.lease_id} not found.")

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=None,
            contract_id=lease.contract_id,
        )

        if record.status not in (BillingRecordStatus.pending, BillingRecordStatus.partially_paid):
            return record

        as_of = as_of or date.today()
        cutoff = record.due_date + timedelta(days=lease.grace_period_days)
        if as_of <= cutoff:
            return record

        self._transition(record, BillingRecordStatus.overdue)

        if not record.late_fee_applied:
            if lease.late_fee_amount is not None:
                fee = lease.late_fee_amount
            else:
                fee = (record.amount_due * lease.late_fee_percent / Decimal("100")).quantize(Decimal("0.01"))
            record.late_fee_amount_charged = fee
            record.late_fee_applied = True

        await db.flush()
        await db.refresh(record)
        write_audit_log(db, current_user, AuditAction.UPDATE, "BillingRecord", record.id)
        await db.commit()
        return record

    @staticmethod
    def _raise_if_already_generated_conflict(e: IntegrityError) -> None:
        """
        Translate a violation of `uq_billing_record_lease_id_period_start`
        into `BillingRecordAlreadyGeneratedError`; leaves unrelated
        IntegrityErrors for the caller to re-raise as is.
        """
        msg = integrity_error_message(e)
        if "uq_billing_record_lease_id_period_start" in msg or ("duplicate key value" in msg and "period_start" in msg):
            raise BillingRecordAlreadyGeneratedError(
                "A BillingRecord already exists for this lease and billing period."
            )
