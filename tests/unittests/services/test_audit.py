from types import SimpleNamespace
from uuid import uuid4

from app.models.audit_log import AuditAction, AuditLog
from app.services.audit import write_audit_log


def _admin(id=None):
    return SimpleNamespace(id=id or uuid4(), role="admin")


class TestWriteAuditLog:
    def test_adds_an_audit_log_to_the_session(self, mock_db):
        actor = _admin()
        entity_id = uuid4()

        write_audit_log(mock_db, actor, AuditAction.CREATE, "Property", entity_id)

        mock_db.add.assert_called_once()
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, AuditLog)
        assert row.actor_id == actor.id
        assert row.action == AuditAction.CREATE
        assert row.entity_type == "Property"
        assert row.entity_id == entity_id
        assert row.diff is None

    def test_includes_diff_when_provided(self, mock_db):
        actor = _admin()
        entity_id = uuid4()
        diff = {"status": ["PAID", "VOIDED"]}

        write_audit_log(mock_db, actor, AuditAction.UPDATE, "Payment", entity_id, diff=diff)

        row = mock_db.add.call_args.args[0]
        assert row.diff == diff

    def test_does_not_flush_or_commit(self, mock_db):
        write_audit_log(mock_db, _admin(), AuditAction.DELETE, "Tenant", uuid4())

        assert not mock_db.commit.called
        assert not mock_db.flush.called

    def test_actor_id_is_none_when_current_user_has_no_id(self, mock_db):
        write_audit_log(mock_db, SimpleNamespace(), AuditAction.CREATE, "User", uuid4())

        row = mock_db.add.call_args.args[0]
        assert row.actor_id is None
