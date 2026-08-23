"""
ARQ background jobs for the recurring-billing engine (see
LeaseBillingService, docs/product/phase-2.md). Manual endpoints
(POST /billing-records/generate, /evaluate-overdue) remain available
for on-demand/backfill use — these jobs call the exact same
LeaseBillingService methods, so the unique-constraint-backed
idempotency (BillingRecordAlreadyGeneratedError) and the
_VALID_TRANSITIONS no-op-on-already-overdue behavior protect against
double-processing whether the trigger was a manager or the scheduler.

Runs as the system-scheduler identity (see scripts/seed_system_user.py)
resolved once in on_startup — that identity is ADMIN-role, which
_authorize_user_to_property already treats as a portfolio-wide no-op
authorization bypass; no service-layer changes were needed.
"""

import logging
from datetime import date

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.dependencies import get_lease_billing_service
from app.db.session import AsyncSessionLocal
from app.db.seed import seed_system_user
from app.repositories.billing_record import billing_record_repo
from app.repositories.lease import lease_repo
from app.services.exceptions import BillingRecordAlreadyGeneratedError

logger = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:
    """Resolve (seeding if necessary) the system-scheduler user once per
    worker process lifetime — it's immutable for that lifetime, and
    reseeding it once per job run would be wasteful at any real lease
    count. Self-seeds via app.db.seed rather than failing if
    scripts/seed_system_user.py wasn't run manually first — a fresh
    environment never needs that separate manual step."""
    async with AsyncSessionLocal() as db:
        system_user, _ = await seed_system_user(db)
    ctx["system_user"] = system_user


async def shutdown(ctx: dict) -> None:
    pass


async def generate_due_billing_records(ctx: dict) -> None:
    """
    Generate the next billing record for every active lease.

    Deliberately doesn't pre-filter "whose period has elapsed" here —
    LeaseBillingService.generate_billing_record already computes the
    correct next period and raises BillingRecordAlreadyGeneratedError if
    that period already has a record. Calling it for every active lease
    every run and treating that as an expected no-op is simpler, and no
    less correct, than duplicating the period-elapsed math here.
    """
    system_user = ctx["system_user"]
    billing_service = get_lease_billing_service()

    async with AsyncSessionLocal() as db:
        leases = await lease_repo.get_active(db)

    generated, skipped = 0, 0
    for lease in leases:
        async with AsyncSessionLocal() as db:
            try:
                await billing_service.generate_billing_record(db, lease.id, system_user)
                generated += 1
            except BillingRecordAlreadyGeneratedError:
                skipped += 1

    logger.info("billing_jobs.generate_due_billing_records: generated=%d skipped=%d", generated, skipped)


async def evaluate_overdue_billing_records(ctx: dict) -> None:
    """
    Re-evaluate overdue status for every non-terminal billing record.
    Reuses BillingRecordRepository.get_unpaid_with_grace — already built
    for the Dashboard's late-payments figure, so no new repository
    method was needed here, unlike the generation side.
    """
    system_user = ctx["system_user"]
    billing_service = get_lease_billing_service()

    async with AsyncSessionLocal() as db:
        records_with_grace = await billing_record_repo.get_unpaid_with_grace(db)

    evaluated = 0
    for record, _grace_period_days in records_with_grace:
        async with AsyncSessionLocal() as db:
            await billing_service.evaluate_overdue(db, record.id, system_user, as_of=date.today())
            evaluated += 1

    logger.info("billing_jobs.evaluate_overdue_billing_records: evaluated=%d", evaluated)


class WorkerSettings:
    functions = [generate_due_billing_records, evaluate_overdue_billing_records]
    cron_jobs = [
        cron(
            generate_due_billing_records,
            hour=settings.BILLING_JOB_CRON_HOUR,
            minute=settings.BILLING_JOB_CRON_MINUTE,
        ),
        cron(
            evaluate_overdue_billing_records,
            hour=settings.BILLING_JOB_CRON_HOUR,
            minute=settings.BILLING_JOB_CRON_MINUTE + 5,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_JOBS_URL)
