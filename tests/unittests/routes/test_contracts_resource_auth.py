from app.core.dependencies import get_current_user
from app.models.user import UserRole
from tests.factories import make_user_model, make_tenant_model, make_property_model


class TestContractsResourceAuth:
    def test_manager_cannot_create_contract_for_unmanaged_property(self, client, db, set_override):
        """Managers may only create contracts for properties they manage."""

        # Create two manager users and a tenant
        manager1 = make_user_model(db, username="mgr1", email="mgr1@example.com", role=UserRole.MANAGER)
        manager2 = make_user_model(db, username="mgr2", email="mgr2@example.com", role=UserRole.MANAGER)
        tenant = make_tenant_model(db)

        # Create a property assigned to manager2
        prop = make_property_model(db, manager_id=manager2.id)

        # Ensure request from manager1 is forbidden for this property
        set_override(get_current_user, lambda: manager1)

        payload = {
            "property_id": str(prop.id),
            "tenant_id": str(tenant.id),
            "rental_type": "long_term",
            "start_date": "2026-01-01",
            "end_date": None,
            "rent_amount": 1000.0,
            "deposit": 500.0,
            "booking_source": "direct",
            "status": "ACTIVE",
        }

        response = client.post("/api/v1/contracts/", json=payload)
        assert response.status_code == 403

        # Assign the property to manager1 and retry — should succeed
        prop.manager_id = manager1.id
        db.add(prop)
        db.commit()

        response = client.post("/api/v1/contracts/", json=payload)
        assert response.status_code == 201
