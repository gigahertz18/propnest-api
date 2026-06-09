import uuid

from app.services.exceptions import ContractActiveError
from app.models.user import UserRole


class TestContractsRoutes:
    def test_create_contract_conflict_returns_409(self, client, set_override, simple_ns):
        from app.core.dependencies import get_contract_service, require_manager_or_above, get_property_service

        class FakeService:
            def create_contract(self, db, payload):
                raise ContractActiveError("conflict")

        set_override(get_contract_service, lambda: FakeService())
        # Provide a fake manager principal so the route-level auth dependency passes
        set_override(require_manager_or_above, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.MANAGER))
        # Ensure property check does not interfere
        set_override(get_property_service, lambda: simple_ns(get_property=lambda db, id: None))

        payload = {
            "property_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "rental_type": "long_term",
            "start_date": "2026-01-01",
            "end_date": None,
            "rent_amount": 1000.0,
            "deposit": 500.0,
            "booking_source": "direct",
            "status": "ACTIVE",
        }

        # use lower-level client fixture to POST
        response = client.post("/api/v1/contracts/", json=payload)
        assert response.status_code == 409

    def test_get_contract_returns_404_when_not_found(self, client, set_override, simple_ns):
        from app.core.dependencies import get_contract_service, require_manager_or_above

        set_override(get_contract_service, lambda: simple_ns(get_contract=lambda db, id: None))
        # Provide a fake manager principal so the route-level auth dependency passes
        set_override(require_manager_or_above, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.MANAGER))

        response = client.get(f"/api/v1/contracts/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_update_contract_forbidden_for_manager(self, client, set_override, simple_ns):
        from app.core.dependencies import get_contract_service, get_property_service, require_manager_or_above

        fake_contract = simple_ns(property_id=uuid.uuid4())
        set_override(get_contract_service, lambda: simple_ns(get_contract=lambda db, id: fake_contract))
        # property_service returns a property managed by someone else
        set_override(
            get_property_service, lambda: simple_ns(get_property=lambda db, id: simple_ns(manager_id=uuid.uuid4()))
        )
        # current user is a manager with a different id
        set_override(require_manager_or_above, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.MANAGER))

        response = client.patch(f"/api/v1/contracts/{uuid.uuid4()}", json={})
        assert response.status_code == 403

    def test_update_contract_returns_404_when_update_not_found(self, client, set_override, simple_ns, admin_user):
        from app.core.dependencies import get_contract_service, require_manager_or_above

        # Admin bypasses manager check
        set_override(require_manager_or_above, lambda: admin_user)
        set_override(
            get_contract_service,
            lambda: simple_ns(
                get_contract=lambda db, id: simple_ns(property_id=uuid.uuid4()),
                update_contract=lambda db, id, payload: None,
            ),
        )

        response = client.patch(f"/api/v1/contracts/{uuid.uuid4()}", json={})
        assert response.status_code == 404

    def test_delete_contract_returns_404_when_delete_not_found(self, client, set_override, simple_ns, admin_user):
        from app.core.dependencies import get_contract_service, require_manager_or_above

        set_override(require_manager_or_above, lambda: admin_user)
        set_override(
            get_contract_service,
            lambda: simple_ns(
                get_contract=lambda db, id: simple_ns(property_id=uuid.uuid4()), delete_contract=lambda db, id: None
            ),
        )

        response = client.delete(f"/api/v1/contracts/{uuid.uuid4()}")
        assert response.status_code == 404
