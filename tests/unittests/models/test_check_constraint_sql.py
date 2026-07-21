"""Regression tests for CHECK constraint SQL generation.

Guards against a previous bug where booking_source/payment_method CHECK
constraints were built by interpolating Python repr()/str() output directly
into SQL text. That approach is fragile: Python's escaping rules aren't SQL's,
and a Python tuple repr for a single-element tuple isn't the SQL `IN (...)`
syntax it happens to resemble.
"""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.db.constraints import sql_in_clause
from app.models.contract import BOOKING_SOURCE, Contract, RentalType
from app.models.payment import PAYMENT_METHODS, Payment
from tests.factories import make_contract_model, make_property_model, make_tenant_model


def _find_check_constraint(table, name: str):
    return next(c for c in table.constraints if getattr(c, "name", None) == name)


class TestSqlInClauseRendering:
    """Unit coverage for the general-purpose helper, independent of any
    particular model's values — these edge cases (quotes, non-ASCII, a
    single value) aren't present in today's BOOKING_SOURCE/PAYMENT_METHODS,
    but the helper must handle them correctly if those lists ever change."""

    def test_multi_value_renders_quoted_comma_separated_list(self):
        rendered = sql_in_clause("booking_source", ("direct", "airbnb", "booking", "agoda"))
        assert rendered == "booking_source IN ('direct', 'airbnb', 'booking', 'agoda')"

    def test_single_value_tuple_renders_valid_in_clause(self):
        # The historical bug: Python's repr of a 1-tuple is "('cash',)" — a
        # trailing comma that happens to still parse as SQL, but by luck,
        # not by design. The helper must render valid IN (...) syntax
        # regardless of how many values there are.
        rendered = sql_in_clause("payment_method", ("cash",))
        assert rendered == "payment_method IN ('cash')"

    def test_value_containing_single_quote_is_escaped(self):
        # repr()/f-string interpolation would emit an unescaped "'" here,
        # producing a syntactically broken (or worse, injectable) clause.
        rendered = sql_in_clause("payment_method", ("o'brien", "cash"))
        assert rendered == "payment_method IN ('o''brien', 'cash')"

    def test_value_containing_non_ascii_characters(self):
        rendered = sql_in_clause("payment_method", ("café", "cash"))
        assert "café" in rendered
        assert rendered.startswith("payment_method IN (")


class TestModelConstraintsUseHelper:
    """Confirms the models actually wire the helper in, not just that the
    helper works in isolation."""

    def test_contract_booking_source_constraint_sql(self):
        constraint = _find_check_constraint(Contract.__table__, "ck_contract_booking_source")
        assert str(constraint.sqltext) == sql_in_clause("booking_source", BOOKING_SOURCE)

    def test_payment_method_constraint_sql(self):
        constraint = _find_check_constraint(Payment.__table__, "ck_payment_method")
        assert str(constraint.sqltext) == sql_in_clause("payment_method", PAYMENT_METHODS)


# ─── Shared fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def property_(db):
    """A persisted Property for FK references."""
    return await make_property_model(db)


@pytest_asyncio.fixture
async def tenant(db):
    """A persisted Tenant for FK references."""
    return await make_tenant_model(db)


@pytest_asyncio.fixture
async def contract_(db, property_, tenant):
    """A persisted, non-ACTIVE contract for Payment FK references.

    status=EXPIRED so it doesn't collide with uq_active_contract_property
    when a test also creates its own ACTIVE/other-status contracts on the
    same property.
    """
    return await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id, status="EXPIRED")


# ─── Real-DB enforcement (the "migration-generation check") ──────────────────
#
# These run the actual rendered CHECK constraint SQL against the project's
# real Postgres test database (via the shared `db` fixture from
# tests/conftest.py), proving it's valid, executable DDL that Postgres
# accepted at table-creation time and genuinely enforces — not just a string
# that looks right.


@pytest.mark.asyncio
class TestContractBookingSourceConstraintOnRealDb:
    async def test_every_declared_booking_source_value_is_accepted(self, db, property_, tenant):
        for value in BOOKING_SOURCE:
            contract = await make_contract_model(
                db,
                property_id=property_.id,
                tenant_id=tenant.id,
                booking_source=value,
                status="EXPIRED",
            )
            assert contract.booking_source == value

    async def test_invalid_booking_source_is_rejected_by_db_constraint(self, db, property_, tenant):
        contract = Contract(
            id=uuid.uuid4(),
            property_id=property_.id,
            tenant_id=tenant.id,
            rental_type=RentalType.long_term,
            start_date=date.today(),
            rent_amount=15000,
            booking_source="not_a_real_platform",
            status="EXPIRED",
        )
        db.add(contract)
        with pytest.raises(IntegrityError):
            await db.flush()


@pytest.mark.asyncio
class TestPaymentMethodConstraintOnRealDb:
    async def test_every_declared_payment_method_is_accepted(self, db, contract_):
        for method in PAYMENT_METHODS:
            payment = Payment(id=uuid.uuid4(), contract_id=contract_.id, amount=1000, payment_method=method)
            db.add(payment)
            await db.flush()
            await db.refresh(payment)
            assert payment.payment_method == method

    async def test_invalid_payment_method_is_rejected_by_db_constraint(self, db, contract_):
        payment = Payment(id=uuid.uuid4(), contract_id=contract_.id, amount=1000, payment_method="bitcoin")
        db.add(payment)
        with pytest.raises(IntegrityError):
            await db.flush()
