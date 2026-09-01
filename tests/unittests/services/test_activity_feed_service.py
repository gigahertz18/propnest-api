import pytest
import uuid

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.models.audit_log import AuditAction, AuditLog
from app.identity.models.user import UserRole
from app.services.activity_feed_service import ActivityFeedService
from app.core.services.exceptions import ActivityFeedForbiddenError, RelatedResourceNotFoundError
from tests.mock_repos import MockReadOnlyRepo


class MockActivityFeedRepo:
    def __init__(
        self,
        property_entries=None,
        contract_entries=None,
        document_entries=None,
        payment_entries=None,
    ):
        self.property_entries = property_entries or []
        self.contract_entries = contract_entries or []
        self.document_entries = document_entries or []
        self.payment_entries = payment_entries or []

    async def get_property_entries(self, db, property_id):
        return self.property_entries

    async def get_contract_entries(self, db, property_id):
        return self.contract_entries

    async def get_document_entries(self, db, property_id):
        return self.document_entries

    async def get_payment_entries(self, db, property_id):
        return self.payment_entries


def _entry(entity_type, created_at, entity_id=None):
    return AuditLog(
        id=uuid.uuid4(),
        actor_id=None,
        action=AuditAction.CREATE,
        entity_type=entity_type,
        entity_id=entity_id or uuid.uuid4(),
        created_at=created_at,
    )


def _make_service(properties=None, activity_feed_repo=None) -> ActivityFeedService:
    property_repo = MockReadOnlyRepo(properties or {})
    return ActivityFeedService(
        activity_feed_repo=activity_feed_repo or MockActivityFeedRepo(),
        property_repo=property_repo,
    )


def _admin():
    return SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)


def _manager(manager_id=None):
    return SimpleNamespace(id=manager_id or uuid.uuid4(), role=UserRole.MANAGER)


@pytest.mark.asyncio
class TestGetPropertyActivity:
    async def test_current_user_is_required(self, mock_db):
        prop = SimpleNamespace(id=uuid.uuid4(), manager_id=uuid.uuid4())
        svc = _make_service(properties={prop.id: prop})

        with pytest.raises(TypeError):
            await svc.get_property_activity(mock_db, prop.id)

    async def test_raises_when_property_not_found(self, mock_db):
        svc = _make_service()

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_property_activity(mock_db, uuid.uuid4(), current_user=_admin())

    async def test_manager_who_does_not_own_property_is_forbidden(self, mock_db):
        prop = SimpleNamespace(id=uuid.uuid4(), manager_id=uuid.uuid4())
        svc = _make_service(properties={prop.id: prop})

        with pytest.raises(ActivityFeedForbiddenError):
            await svc.get_property_activity(mock_db, prop.id, current_user=_manager())

    async def test_admin_bypasses_ownership_check(self, mock_db):
        manager_id = uuid.uuid4()
        prop = SimpleNamespace(id=uuid.uuid4(), manager_id=manager_id)
        repo = MockActivityFeedRepo(property_entries=[_entry("Property", datetime.now(timezone.utc))])
        svc = _make_service(properties={prop.id: prop}, activity_feed_repo=repo)

        result = await svc.get_property_activity(mock_db, prop.id, current_user=_admin())

        assert result.total == 1

    async def test_manager_can_view_owned_propertys_activity(self, mock_db):
        manager_id = uuid.uuid4()
        prop = SimpleNamespace(id=uuid.uuid4(), manager_id=manager_id)
        repo = MockActivityFeedRepo(property_entries=[_entry("Property", datetime.now(timezone.utc))])
        svc = _make_service(properties={prop.id: prop}, activity_feed_repo=repo)

        result = await svc.get_property_activity(mock_db, prop.id, current_user=_manager(manager_id))

        assert result.total == 1

    async def test_merges_entries_from_all_four_branches(self, mock_db):
        prop = SimpleNamespace(id=uuid.uuid4(), manager_id=uuid.uuid4())
        now = datetime.now(timezone.utc)
        repo = MockActivityFeedRepo(
            property_entries=[_entry("Property", now)],
            contract_entries=[_entry("Contract", now)],
            document_entries=[_entry("Document", now)],
            payment_entries=[_entry("Payment", now)],
        )
        svc = _make_service(properties={prop.id: prop}, activity_feed_repo=repo)

        result = await svc.get_property_activity(mock_db, prop.id, current_user=_admin())

        assert result.total == 4
        assert {e.entity_type for e in result.items} == {"Property", "Contract", "Document", "Payment"}

    async def test_sorts_entries_by_created_at_descending(self, mock_db):
        prop = SimpleNamespace(id=uuid.uuid4(), manager_id=uuid.uuid4())
        now = datetime.now(timezone.utc)
        oldest = _entry("Property", now - timedelta(days=2))
        middle = _entry("Contract", now - timedelta(days=1))
        newest = _entry("Payment", now)
        repo = MockActivityFeedRepo(
            property_entries=[oldest],
            contract_entries=[middle],
            payment_entries=[newest],
        )
        svc = _make_service(properties={prop.id: prop}, activity_feed_repo=repo)

        result = await svc.get_property_activity(mock_db, prop.id, current_user=_admin())

        assert [e.id for e in result.items] == [newest.id, middle.id, oldest.id]

    async def test_applies_skip_and_limit_after_merging(self, mock_db):
        prop = SimpleNamespace(id=uuid.uuid4(), manager_id=uuid.uuid4())
        now = datetime.now(timezone.utc)
        entries = [_entry("Property", now - timedelta(days=i)) for i in range(5)]
        repo = MockActivityFeedRepo(property_entries=entries)
        svc = _make_service(properties={prop.id: prop}, activity_feed_repo=repo)

        result = await svc.get_property_activity(mock_db, prop.id, current_user=_admin(), skip=1, limit=2)

        assert result.total == 5
        assert len(result.items) == 2
        assert result.items[0].id == entries[1].id
        assert result.items[1].id == entries[2].id
