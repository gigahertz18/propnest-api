import pytest
import uuid

from app.services.exceptions import ContractActiveError
from app.models.user import UserRole
from app.core.dependencies import get_contract_service, get_property_service, require_manager_or_above

from unittest.mock import AsyncMock

@pytest.mark.asyncio
class TestContractsRoutes:
    async def test_create_contract_conflict_returns_409(self, client, set_override, simple_ns):

        class FakeService:
            async def create_contract(self, db, payload):
                raise ContractActiveError("conflict")
            
        prop_id = uuid.uuid4()
        manager_id = uuid.uuid4()
        # Property owned by another manager
        prop = simple_ns(id=prop_id, manager_id=manager_id)

        set_override(get_contract_service, lambda: FakeService())
        # Provide a fake manager principal so the route-level auth dependency passes
        set_override(require_manager_or_above, lambda: simple_ns(id=manager_id, role=UserRole.MANAGER))
        # Ensure property check does not interfere
        set_override(get_property_service, lambda: simple_ns(get_property=AsyncMock(return_value=prop)))

        payload = {
            "property_id": str(prop_id),
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
        response = await client.post("/api/v1/contracts/", json=payload)
        assert response.status_code == 409

    async def test_get_contract_returns_404_when_not_found(self, client, set_override, simple_ns):

        set_override(get_contract_service, lambda: simple_ns(get_contract=AsyncMock(return_value=None)))
        # Provide a fake manager principal so the route-level auth dependency passes
        set_override(require_manager_or_above, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.MANAGER))

        response = await client.get(f"/api/v1/contracts/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_update_contract_forbidden_for_manager(self, client, set_override, simple_ns):

        fake_contract = simple_ns(property_id=uuid.uuid4())
        fake_manager = simple_ns(manager_id=uuid.uuid4())
        set_override(get_contract_service, lambda: simple_ns(get_contract=AsyncMock(return_value=fake_contract)))
        # property_service returns a property managed by someone else
        set_override(
            get_property_service, lambda: simple_ns(get_property=AsyncMock(return_value=fake_manager))
        )
        # current user is a manager with a different id
        set_override(require_manager_or_above, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.MANAGER))

        response = await client.patch(f"/api/v1/contracts/{uuid.uuid4()}", json={})
        assert response.status_code == 403

    async def test_update_contract_returns_404_when_update_not_found(self, client, set_override, simple_ns, admin_user):
        
        fake_contract = simple_ns(property_id=uuid.uuid4())
        # Admin bypasses manager check
        set_override(require_manager_or_above, lambda: admin_user)
        set_override(
            get_contract_service,
            lambda: simple_ns(
                get_contract=AsyncMock(return_value=fake_contract),
                update_contract=AsyncMock(return_value=None),
            ),
        )

        response = await client.patch(f"/api/v1/contracts/{uuid.uuid4()}", json={})
        assert response.status_code == 404

    async def test_delete_contract_returns_404_when_delete_not_found(self, client, set_override, simple_ns, admin_user):

        fake_contract = simple_ns(property_id=uuid.uuid4())
        set_override(require_manager_or_above, lambda: admin_user)
        set_override(
            get_contract_service,
            lambda: simple_ns(
                get_contract=AsyncMock(return_value=fake_contract), 
                delete_contract=AsyncMock(return_value=None)
            ),
        )

        response = await client.delete(f"/api/v1/contracts/{uuid.uuid4()}")
        assert response.status_code == 404
