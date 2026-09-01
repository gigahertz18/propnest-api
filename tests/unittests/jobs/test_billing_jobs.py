from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.jobs.billing_jobs import (
    evaluate_overdue_billing_records,
    generate_due_billing_records,
)
from app.core.services.exceptions import BillingRecordAlreadyGeneratedError
from tests.factories import make_admin


@pytest.fixture
def ctx():
    """Mimics arq's job context dict — the system user is resolved once
    in on_startup and threaded through, not re-fetched per job run."""
    return {"system_user": make_admin()}


@pytest.mark.asyncio
class TestGenerateDueBillingRecords:
    async def test_generates_for_every_active_lease(self, ctx, monkeypatch):
        leases = [type("L", (), {"id": uuid4()})() for _ in range(3)]
        mock_lease_repo = AsyncMock()
        mock_lease_repo.get_active.return_value = leases
        mock_service = AsyncMock()
        monkeypatch.setattr("app.jobs.billing_jobs.lease_repo", mock_lease_repo)
        monkeypatch.setattr("app.jobs.billing_jobs.get_lease_billing_service", lambda: mock_service)

        await generate_due_billing_records(ctx)

        assert mock_service.generate_billing_record.await_count == 3

    async def test_swallows_already_generated_for_the_other_leases(self, ctx, monkeypatch):
        """A lease whose period hasn't elapsed yet still gets called — the
        job doesn't pre-compute eligibility, LeaseBillingService already
        does via period math — so BillingRecordAlreadyGeneratedError is
        expected and must not abort the run for the remaining leases."""
        leases = [type("L", (), {"id": uuid4()})() for _ in range(2)]
        mock_lease_repo = AsyncMock()
        mock_lease_repo.get_active.return_value = leases
        mock_service = AsyncMock()
        mock_service.generate_billing_record.side_effect = [
            BillingRecordAlreadyGeneratedError("already exists"),
            None,
        ]
        monkeypatch.setattr("app.jobs.billing_jobs.lease_repo", mock_lease_repo)
        monkeypatch.setattr("app.jobs.billing_jobs.get_lease_billing_service", lambda: mock_service)

        await generate_due_billing_records(ctx)  # must not raise

        assert mock_service.generate_billing_record.await_count == 2


@pytest.mark.asyncio
class TestEvaluateOverdueBillingRecords:
    async def test_evaluates_every_non_terminal_record(self, ctx, monkeypatch):
        mock_billing_repo = AsyncMock()
        mock_billing_repo.get_unpaid_with_grace.return_value = [
            (type("R", (), {"id": uuid4()})(), 3),
            (type("R", (), {"id": uuid4()})(), 5),
        ]
        mock_service = AsyncMock()
        monkeypatch.setattr("app.jobs.billing_jobs.billing_record_repo", mock_billing_repo)
        monkeypatch.setattr("app.jobs.billing_jobs.get_lease_billing_service", lambda: mock_service)

        await evaluate_overdue_billing_records(ctx)

        assert mock_service.evaluate_overdue.await_count == 2
