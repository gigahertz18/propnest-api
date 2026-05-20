from types import SimpleNamespace

from app.services.exceptions import ContractActiveError


def test_create_contract_conflict_returns_409(client):
    from app.main import app
    from app.core.dependencies import get_contract_service, require_manager_or_above
    import uuid
    from types import SimpleNamespace

    class FakeService:
        def create_contract(self, db, payload):
            raise ContractActiveError("conflict")

    app.dependency_overrides[get_contract_service] = lambda: FakeService()
    # Provide a fake manager principal so the route-level auth dependency passes
    app.dependency_overrides[require_manager_or_above] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role=SimpleNamespace(value="manager")
    )

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

    app.dependency_overrides.pop(get_contract_service, None)
    app.dependency_overrides.pop(require_manager_or_above, None)
