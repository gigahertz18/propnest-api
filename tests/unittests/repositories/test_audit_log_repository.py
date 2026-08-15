import pytest
import uuid

from app.models.audit_log import AuditAction, AuditLog
from app.repositories.audit_log import audit_log_repo


def _row(entity_type="Property", entity_id=None, action=AuditAction.CREATE, actor_id=None):
    """`actor_id` defaults to None (nullable FK) — these tests exercise
    entity_type/entity_id filtering, not actor identity, so there's no
    need to persist a real `User` row just to satisfy the FK."""
    return AuditLog(
        id=uuid.uuid4(),
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id or uuid.uuid4(),
    )


@pytest.mark.asyncio
class TestAuditLogRepositoryGetFiltered:
    async def test_returns_empty_list_when_no_rows(self, db):
        result = await audit_log_repo.get_filtered(db)
        assert list(result) == []

    async def test_returns_all_rows_when_no_filters(self, db):
        db.add(_row(entity_type="Property"))
        db.add(_row(entity_type="Payment"))
        await db.flush()

        result = await audit_log_repo.get_filtered(db)
        assert len(result) == 2

    async def test_filters_by_entity_type(self, db):
        db.add(_row(entity_type="Property"))
        db.add(_row(entity_type="Payment"))
        await db.flush()

        result = await audit_log_repo.get_filtered(db, entity_type="Payment")
        assert len(result) == 1
        assert result[0].entity_type == "Payment"

    async def test_filters_by_entity_id(self, db):
        target_id = uuid.uuid4()
        db.add(_row(entity_type="Property", entity_id=target_id))
        db.add(_row(entity_type="Property", entity_id=uuid.uuid4()))
        await db.flush()

        result = await audit_log_repo.get_filtered(db, entity_id=target_id)
        assert len(result) == 1
        assert result[0].entity_id == target_id

    async def test_filters_by_entity_type_and_entity_id_together(self, db):
        target_id = uuid.uuid4()
        db.add(_row(entity_type="Property", entity_id=target_id, action=AuditAction.CREATE))
        db.add(_row(entity_type="Payment", entity_id=target_id, action=AuditAction.CREATE))
        await db.flush()

        result = await audit_log_repo.get_filtered(db, entity_type="Property", entity_id=target_id)
        assert len(result) == 1
        assert result[0].entity_type == "Property"
        assert result[0].entity_id == target_id

    async def test_respects_skip_and_limit(self, db):
        for _ in range(3):
            db.add(_row(entity_type="Property"))
        await db.flush()

        result = await audit_log_repo.get_filtered(db, skip=1, limit=1)
        assert len(result) == 1


@pytest.mark.asyncio
class TestAuditLogRepositoryCountFiltered:
    async def test_counts_all_when_no_filters(self, db):
        db.add(_row(entity_type="Property"))
        db.add(_row(entity_type="Payment"))
        await db.flush()

        count = await audit_log_repo.count_filtered(db)
        assert count == 2

    async def test_counts_matching_entity_type_only(self, db):
        db.add(_row(entity_type="Property"))
        db.add(_row(entity_type="Payment"))
        await db.flush()

        count = await audit_log_repo.count_filtered(db, entity_type="Property")
        assert count == 1
