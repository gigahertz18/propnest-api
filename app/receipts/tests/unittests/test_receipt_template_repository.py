import pytest
import pytest_asyncio

from app.receipts.repositories.receipt_template import receipt_template_repo
from tests.factories import make_property_model


@pytest_asyncio.fixture
async def property_(db):
    return await make_property_model(db)


def _payload(property_id=None, is_active=False, name="Default"):
    return {
        "name": name,
        "property_id": property_id,
        "storage_key": "receipt_templates/x.html",
        "file_url": "http://minio/propnest-contracts/receipt_templates/x.html",
        "is_active": is_active,
    }


@pytest.mark.asyncio
class TestGetActiveForProperty:
    async def test_returns_the_active_row_for_that_property(self, db, property_):
        await receipt_template_repo.create(db, _payload(property_id=property_.id, is_active=False))
        active = await receipt_template_repo.create(db, _payload(property_id=property_.id, is_active=True))

        result = await receipt_template_repo.get_active_for_property(db, property_.id)
        assert result.id == active.id

    async def test_returns_none_when_no_active_row(self, db, property_):
        await receipt_template_repo.create(db, _payload(property_id=property_.id, is_active=False))
        result = await receipt_template_repo.get_active_for_property(db, property_.id)
        assert result is None


@pytest.mark.asyncio
class TestGetActiveGlobal:
    async def test_returns_the_active_global_row(self, db):
        active = await receipt_template_repo.create(db, _payload(property_id=None, is_active=True))
        result = await receipt_template_repo.get_active_global(db)
        assert result.id == active.id

    async def test_does_not_return_property_scoped_rows(self, db, property_):
        await receipt_template_repo.create(db, _payload(property_id=property_.id, is_active=True))
        result = await receipt_template_repo.get_active_global(db)
        assert result is None


@pytest.mark.asyncio
class TestGetByProperty:
    async def test_returns_all_rows_for_that_property(self, db, property_):
        t1 = await receipt_template_repo.create(db, _payload(property_id=property_.id, name="a"))
        t2 = await receipt_template_repo.create(db, _payload(property_id=property_.id, name="b"))

        results = await receipt_template_repo.get_by_property(db, property_.id)
        assert {r.id for r in results} == {t1.id, t2.id}


@pytest.mark.asyncio
class TestActiveScopeUniqueness:
    async def test_only_one_active_row_allowed_per_property(self, db, property_):
        from sqlalchemy.exc import IntegrityError

        await receipt_template_repo.create(db, _payload(property_id=property_.id, is_active=True))
        with pytest.raises(IntegrityError):
            await receipt_template_repo.create(db, _payload(property_id=property_.id, is_active=True))

    async def test_only_one_active_global_row_allowed(self, db):
        from sqlalchemy.exc import IntegrityError

        await receipt_template_repo.create(db, _payload(property_id=None, is_active=True))
        with pytest.raises(IntegrityError):
            await receipt_template_repo.create(db, _payload(property_id=None, is_active=True))
