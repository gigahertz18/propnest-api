import pytest

from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from app.core.models.audit_log import AuditAction, AuditLog
from app.core.services.exceptions import (
    ReceiptTemplateForbiddenError,
    ReceiptTemplateUploadError,
    ReceiptTemplateValidationError,
    RelatedResourceNotFoundError,
    ResourceForbiddenError,
)
from app.receipts.services.receipt_pdf import load_default_template
from app.receipts.services.receipt_template_service import ReceiptTemplateService
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_admin, make_manager, make_regular_user


class MockReceiptTemplateRepo(MockCRUDRepo):
    async def get_active_for_property(self, db, property_id):
        matches = await self._filter_by(property_id=property_id, is_active=True)
        return matches[0] if matches else None

    async def get_active_global(self, db):
        matches = [r for r in self.records.values() if r.property_id is None and r.is_active]
        return matches[0] if matches else None

    async def get_by_property(self, db, property_id):
        return await self._filter_by(property_id=property_id)

    async def get_global_templates(self, db):
        return [r for r in self.records.values() if r.property_id is None]


class FakeStorageClient:
    def __init__(self, raise_on_put=None):
        self.raise_on_put = raise_on_put
        self.objects: dict[str, bytes] = {}

    def put_object(self, bucket, key, stream, length, content_type=None):
        if self.raise_on_put:
            raise self.raise_on_put
        self.objects[key] = stream.read()

    def get_object(self, bucket, key):
        data = self.objects[key]

        class _Response:
            def read(self_inner):
                return data

            def close(self_inner):
                pass

            def release_conn(self_inner):
                pass

        return _Response()

    def remove_object(self, bucket, key):
        self.objects.pop(key, None)


def _make_service(templates=None, properties=None) -> ReceiptTemplateService:
    receipt_template_repo = templates if templates is not None else MockReceiptTemplateRepo({})
    property_repo = properties if properties is not None else MockReadOnlyRepo({})
    return ReceiptTemplateService(receipt_template_repo=receipt_template_repo, property_repo=property_repo)


def _html_file(content: bytes = b"<html><body>{{ receipt_number }}</body></html>"):
    return BytesIO(content)


class TestReceiptTemplateServiceClassAttributes:
    def test_forbidden_error_is_receipt_template_forbidden_error(self):
        assert ReceiptTemplateService.forbidden_error is ReceiptTemplateForbiddenError

    def test_is_a_resource_forbidden_error(self):
        assert issubclass(ReceiptTemplateForbiddenError, ResourceForbiddenError)


@pytest.mark.asyncio
class TestUploadTemplate:
    async def test_admin_can_upload_global_template(self, mock_db):
        svc = _make_service()
        admin = make_admin()

        template = await svc.upload_template(
            mock_db, "Global Default", None, admin, storage_client=FakeStorageClient(), file_obj=_html_file()
        )

        assert template.property_id is None
        assert template.is_active is False
        assert mock_db.commit.called

    async def test_manager_cannot_upload_global_template(self, mock_db):
        svc = _make_service()
        with pytest.raises(ReceiptTemplateForbiddenError):
            await svc.upload_template(
                mock_db,
                "Global Default",
                None,
                make_manager(),
                storage_client=FakeStorageClient(),
                file_obj=_html_file(),
            )

    async def test_manager_can_upload_for_owned_property(self, mock_db):
        manager_id, prop_id = uuid4(), uuid4()
        svc = _make_service(properties=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)}))

        template = await svc.upload_template(
            mock_db,
            "Branded Receipt",
            prop_id,
            make_manager(manager_id),
            storage_client=FakeStorageClient(),
            file_obj=_html_file(),
        )
        assert template.property_id == prop_id

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        prop_id = uuid4()
        svc = _make_service(properties=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}))

        with pytest.raises(ReceiptTemplateForbiddenError):
            await svc.upload_template(
                mock_db,
                "Branded Receipt",
                prop_id,
                make_manager(),
                storage_client=FakeStorageClient(),
                file_obj=_html_file(),
            )

    async def test_user_role_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(ReceiptTemplateForbiddenError):
            await svc.upload_template(
                mock_db, "x", None, make_regular_user(), storage_client=FakeStorageClient(), file_obj=_html_file()
            )

    async def test_raises_when_property_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.upload_template(
                mock_db, "x", uuid4(), make_admin(), storage_client=FakeStorageClient(), file_obj=_html_file()
            )

    async def test_raises_on_storage_failure(self, mock_db):
        svc = _make_service()
        with pytest.raises(ReceiptTemplateUploadError):
            await svc.upload_template(
                mock_db,
                "x",
                None,
                make_admin(),
                storage_client=FakeStorageClient(raise_on_put=RuntimeError("boom")),
                file_obj=_html_file(),
            )

    async def test_raises_when_file_is_not_valid_utf8(self, mock_db):
        svc = _make_service()
        with pytest.raises(ReceiptTemplateValidationError):
            await svc.upload_template(
                mock_db,
                "x",
                None,
                make_admin(),
                storage_client=FakeStorageClient(),
                file_obj=_html_file(b"\xff\xfe\x00"),
            )

    async def test_raises_when_file_too_large(self, mock_db):
        svc = _make_service()
        oversized = b"a" * (512 * 1024 + 1)
        with pytest.raises(ReceiptTemplateValidationError):
            await svc.upload_template(
                mock_db, "x", None, make_admin(), storage_client=FakeStorageClient(), file_obj=_html_file(oversized)
            )

    async def test_writes_audit_log(self, mock_db):
        svc = _make_service()
        admin = make_admin()
        template = await svc.upload_template(
            mock_db, "x", None, admin, storage_client=FakeStorageClient(), file_obj=_html_file()
        )
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, AuditLog)
        assert row.action == AuditAction.CREATE
        assert row.entity_type == "ReceiptTemplate"
        assert row.entity_id == template.id


@pytest.mark.asyncio
class TestActivateTemplate:
    async def test_activating_deactivates_previous_active_in_same_scope(self, mock_db):
        prop_id = uuid4()
        templates_repo = MockReceiptTemplateRepo(
            {
                "old": SimpleNamespace(id="old", property_id=prop_id, is_active=True),
                "new": SimpleNamespace(id="new", property_id=prop_id, is_active=False),
            }
        )
        svc = _make_service(
            templates=templates_repo,
            properties=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
        )

        result = await svc.activate_template(mock_db, "new", make_admin())

        assert result.is_active is True
        assert templates_repo.records["old"].is_active is False
        assert mock_db.commit.called

    async def test_activating_global_scope_deactivates_previous_global(self, mock_db):
        templates_repo = MockReceiptTemplateRepo(
            {
                "old": SimpleNamespace(id="old", property_id=None, is_active=True),
                "new": SimpleNamespace(id="new", property_id=None, is_active=False),
            }
        )
        svc = _make_service(templates=templates_repo)

        result = await svc.activate_template(mock_db, "new", make_admin())

        assert result.is_active is True
        assert templates_repo.records["old"].is_active is False

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        prop_id = uuid4()
        templates_repo = MockReceiptTemplateRepo({"t": SimpleNamespace(id="t", property_id=prop_id, is_active=False)})
        svc = _make_service(
            templates=templates_repo,
            properties=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
        )

        with pytest.raises(ReceiptTemplateForbiddenError):
            await svc.activate_template(mock_db, "t", make_manager())

    async def test_manager_cannot_activate_global_template(self, mock_db):
        templates_repo = MockReceiptTemplateRepo({"t": SimpleNamespace(id="t", property_id=None, is_active=False)})
        svc = _make_service(templates=templates_repo)

        with pytest.raises(ReceiptTemplateForbiddenError):
            await svc.activate_template(mock_db, "t", make_manager())

    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.activate_template(mock_db, uuid4(), make_admin())


@pytest.mark.asyncio
class TestResolveActiveTemplateHtml:
    async def test_falls_back_to_default_when_nothing_active(self, mock_db):
        svc = _make_service()
        html = await svc.resolve_active_template_html(mock_db, uuid4(), FakeStorageClient())
        assert html == load_default_template()

    async def test_uses_property_specific_active_template_over_global(self, mock_db):
        prop_id = uuid4()
        storage = FakeStorageClient()
        storage.objects["receipt_templates/prop.html"] = b"<html>property-specific</html>"
        storage.objects["receipt_templates/global.html"] = b"<html>global</html>"

        templates_repo = MockReceiptTemplateRepo(
            {
                "prop": SimpleNamespace(
                    id="prop", property_id=prop_id, is_active=True, storage_key="receipt_templates/prop.html"
                ),
                "global": SimpleNamespace(
                    id="global", property_id=None, is_active=True, storage_key="receipt_templates/global.html"
                ),
            }
        )
        svc = _make_service(templates=templates_repo)

        html = await svc.resolve_active_template_html(mock_db, prop_id, storage)
        assert html == "<html>property-specific</html>"

    async def test_falls_back_to_global_when_property_has_no_active_template(self, mock_db):
        prop_id = uuid4()
        storage = FakeStorageClient()
        storage.objects["receipt_templates/global.html"] = b"<html>global</html>"

        templates_repo = MockReceiptTemplateRepo(
            {
                "global": SimpleNamespace(
                    id="global", property_id=None, is_active=True, storage_key="receipt_templates/global.html"
                )
            }
        )
        svc = _make_service(templates=templates_repo)

        html = await svc.resolve_active_template_html(mock_db, prop_id, storage)
        assert html == "<html>global</html>"


@pytest.mark.asyncio
class TestListAndGetTemplate:
    async def test_admin_can_list_all_templates(self, mock_db):
        templates_repo = MockReceiptTemplateRepo({"a": SimpleNamespace(id="a", property_id=None, is_active=False)})
        svc = _make_service(templates=templates_repo)
        result = await svc.list_templates(mock_db, make_admin())
        assert len(result) == 1

    async def test_manager_forbidden_from_listing_everything(self, mock_db):
        svc = _make_service()
        with pytest.raises(ReceiptTemplateForbiddenError):
            await svc.list_templates(mock_db, make_manager())

    async def test_manager_can_list_for_owned_property(self, mock_db):
        manager_id, prop_id = uuid4(), uuid4()
        templates_repo = MockReceiptTemplateRepo({"a": SimpleNamespace(id="a", property_id=prop_id, is_active=False)})
        svc = _make_service(
            templates=templates_repo,
            properties=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)}),
        )
        result = await svc.list_templates(mock_db, make_manager(manager_id), property_id=prop_id)
        assert len(result) == 1

    async def test_get_template_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_template(mock_db, uuid4(), make_admin())
