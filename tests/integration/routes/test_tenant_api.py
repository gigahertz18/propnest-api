import pytest
import uuid

from app.models.user import UserRole
from tests.factories import (
    make_tenant,
    make_tenant_model,
    make_user_model,
    make_property_model,
    make_contract_model,
)


async def _make_owned_tenant(db, manager_id, **tenant_kwargs):
    """Build a tenant tied via a contract to a property owned by manager_id."""
    prop = await make_property_model(db, manager_id=manager_id)
    tenant = await make_tenant_model(db, **tenant_kwargs)
    await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
    return tenant


@pytest.mark.asyncio
class TestListTenantsRoute:
    async def test_returns_empty_list(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        response = await client.get("/api/v1/tenants/", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    async def test_admin_sees_all_tenants(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        await make_tenant_model(db, email="tenant_a@example.com")
        await make_tenant_model(db, email="tenant_b@example.com")

        response = await client.get("/api/v1/tenants/", headers=ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 2
        assert len(resp_data["items"]) == 2

    async def test_admin_sees_all_tenants_with_pagination(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        await make_tenant_model(db, email="tenant_a@example.com")
        await make_tenant_model(db, email="tenant_b@example.com")

        response = await client.get("/api/v1/tenants/?skip=1&limit=1", headers=ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 2
        assert len(resp_data["items"]) == 1

    async def test_manager_sees_unclaimed_and_own_tenants(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr", email="othermgr@example.com", role=UserRole.MANAGER
        )

        unclaimed = await make_tenant_model(db, email="unclaimed@example.com")
        owned = await _make_owned_tenant(db, ctx.user.id, email="owned@example.com")
        await _make_owned_tenant(db, other_manager.id, email="not_mine@example.com")

        response = await client.get("/api/v1/tenants/", headers=ctx.headers)
        assert response.status_code == 200
        ids = {t["id"] for t in response.json()["items"]}
        assert ids == {str(unclaimed.id), str(owned.id)}

    async def test_regular_user_cannot_list_tenants(self, client, authenticate_user):
        ctx = await authenticate_user()
        response = await client.get("/api/v1/tenants/", headers=ctx.headers)
        assert response.status_code == 403

    async def test_unauthenticated_cannot_list_tenants(self, client):
        response = await client.get("/api/v1/tenants/")
        assert response.status_code == 403


@pytest.mark.asyncio
class TestGetTenantRoute:
    async def test_manager_can_get_unclaimed_tenant(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        response = await client.get(f"/api/v1/tenants/{tenant.id}", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(tenant.id)

    async def test_manager_can_get_own_tenant(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        tenant = await _make_owned_tenant(db, ctx.user.id)
        response = await client.get(f"/api/v1/tenants/{tenant.id}", headers=ctx.headers)
        assert response.status_code == 200

    async def test_manager_cannot_get_another_managers_tenant(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr", email="othermgr@example.com", role=UserRole.MANAGER
        )
        tenant = await _make_owned_tenant(db, other_manager.id)

        response = await client.get(f"/api/v1/tenants/{tenant.id}", headers=ctx.headers)
        assert response.status_code == 403

    async def test_admin_can_get_any_tenant(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        other_manager = await make_user_model(
            db, username="othermgr", email="othermgr@example.com", role=UserRole.MANAGER
        )
        tenant = await _make_owned_tenant(db, other_manager.id)

        response = await client.get(f"/api/v1/tenants/{tenant.id}", headers=ctx.headers)
        assert response.status_code == 200

    async def test_regular_user_cannot_get_tenant(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        tenant = await make_tenant_model(db)
        response = await client.get(f"/api/v1/tenants/{tenant.id}", headers=ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_when_not_found(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        response = await client.get(f"/api/v1/tenants/{uuid.uuid4()}", headers=ctx.headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
class TestCreateTenantRoute:
    async def test_creates_tenant_successfully(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        payload = make_tenant(full_name="New Tenant", email="new_tenant@example.com")
        payload["date_of_birth"] = payload["date_of_birth"].isoformat()
        response = await client.post(
            "/api/v1/tenants/",
            json=payload,
            headers=ctx.headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["full_name"] == "New Tenant"
        assert data["id"] is not None
        assert data["created_at"] is not None
        # Not yet linked to a portal-access User account.
        assert data["user_id"] is None

    async def test_returns_422_when_email_missing(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        payload = make_tenant()
        payload["date_of_birth"] = payload["date_of_birth"].isoformat()
        del payload["email"]
        response = await client.post(
            "/api/v1/tenants/",
            json=payload,
            headers=ctx.headers,
        )
        assert response.status_code == 422

    async def test_regular_user_cannot_create_tenant(self, client, authenticate_user):
        ctx = await authenticate_user()
        payload = make_tenant(email="blocked@example.com")
        payload["date_of_birth"] = payload["date_of_birth"].isoformat()
        response = await client.post(
            "/api/v1/tenants/",
            json=payload,
            headers=ctx.headers,
        )
        assert response.status_code == 403


@pytest.mark.asyncio
class TestUpdateTenantRoute:
    async def test_updates_full_name(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        tenant = await make_tenant_model(db, full_name="Old Name")
        response = await client.patch(
            f"/api/v1/tenants/{tenant.id}",
            json={"full_name": "New Name"},
            headers=ctx.headers,
        )

        assert response.status_code == 200
        assert response.json()["full_name"] == "New Name"

    async def test_partial_update_does_not_affect_other_fields(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        tenant = await make_tenant_model(db, full_name="Alice", occupation="Engineer")
        response = await client.patch(
            f"/api/v1/tenants/{tenant.id}",
            json={"full_name": "Alice Updated"},
            headers=ctx.headers,
        )

        assert response.json()["occupation"] == "Engineer"

    async def test_returns_404_when_not_found(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        response = await client.patch(
            f"/api/v1/tenants/{uuid.uuid4()}",
            json={"full_name": "Anything"},
            headers=ctx.headers,
        )
        assert response.status_code == 404

    async def test_manager_cannot_update_another_managers_tenant(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr", email="othermgr@example.com", role=UserRole.MANAGER
        )
        tenant = await _make_owned_tenant(db, other_manager.id)

        response = await client.patch(
            f"/api/v1/tenants/{tenant.id}",
            json={"full_name": "Hacked"},
            headers=ctx.headers,
        )
        assert response.status_code == 403

    async def test_regular_user_cannot_update_tenant(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        tenant = await make_tenant_model(db)
        response = await client.patch(
            f"/api/v1/tenants/{tenant.id}",
            json={"full_name": "Hacked"},
            headers=ctx.headers,
        )
        assert response.status_code == 403


@pytest.mark.asyncio
class TestDeleteTenantRoute:
    async def test_deletes_tenant_successfully(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        response = await client.delete(
            f"/api/v1/tenants/{tenant.id}",
            headers=ctx.headers,
        )
        assert response.status_code == 204

    async def test_deleted_tenant_is_gone(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        tenant_id = tenant.id
        await client.delete(f"/api/v1/tenants/{tenant_id}", headers=ctx.headers)
        response = await client.get(f"/api/v1/tenants/{tenant_id}", headers=ctx.headers)
        assert response.status_code == 404

    async def test_returns_404_when_not_found(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        response = await client.delete(
            f"/api/v1/tenants/{uuid.uuid4()}",
            headers=ctx.headers,
        )
        assert response.status_code == 404

    async def test_regular_user_cannot_delete(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        tenant = await make_tenant_model(db)
        response = await client.delete(
            f"/api/v1/tenants/{tenant.id}",
            headers=ctx.headers,
        )
        assert response.status_code == 403

    async def test_manager_cannot_delete_another_managers_tenant(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr", email="othermgr@example.com", role=UserRole.MANAGER
        )
        tenant = await _make_owned_tenant(db, other_manager.id)

        response = await client.delete(
            f"/api/v1/tenants/{tenant.id}",
            headers=ctx.headers,
        )
        assert response.status_code == 403


@pytest.mark.asyncio
class TestLinkTenantUserRoute:
    async def test_manager_can_link_tenant_to_user(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        user = await make_user_model(db, username="portal_user", email="portal_user@example.com")

        response = await client.put(
            f"/api/v1/tenants/{tenant.id}/link-user",
            json={"user_id": str(user.id)},
            headers=ctx.headers,
        )

        assert response.status_code == 200
        assert response.json()["user_id"] == str(user.id)

    async def test_manager_cannot_link_another_managers_tenant(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await authenticate_manager(username="othermgr", email="othermgr@example.com")
        tenant = await _make_owned_tenant(db, other_manager.user.id)
        user = await make_user_model(db, username="portal_user", email="portal_user@example.com")

        response = await client.put(
            f"/api/v1/tenants/{tenant.id}/link-user",
            json={"user_id": str(user.id)},
            headers=ctx.headers,
        )

        assert response.status_code == 403

    async def test_returns_404_when_tenant_not_found(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        user = await make_user_model(db, username="portal_user2", email="portal_user2@example.com")

        response = await client.put(
            f"/api/v1/tenants/{uuid.uuid4()}/link-user",
            json={"user_id": str(user.id)},
            headers=ctx.headers,
        )

        assert response.status_code == 404

    async def test_returns_404_when_user_not_found(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)

        response = await client.put(
            f"/api/v1/tenants/{tenant.id}/link-user",
            json={"user_id": str(uuid.uuid4())},
            headers=ctx.headers,
        )

        assert response.status_code == 404

    async def test_returns_409_when_tenant_already_linked_to_different_user(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        first_user = await make_user_model(db, username="first_user", email="first_user@example.com")
        second_user = await make_user_model(db, username="second_user", email="second_user@example.com")
        tenant = await make_tenant_model(db, user_id=first_user.id)

        response = await client.put(
            f"/api/v1/tenants/{tenant.id}/link-user",
            json={"user_id": str(second_user.id)},
            headers=ctx.headers,
        )

        assert response.status_code == 409

    async def test_returns_409_when_user_already_linked_to_different_tenant(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        user = await make_user_model(db, username="shared_user", email="shared_user@example.com")
        await make_tenant_model(db, user_id=user.id, email="already_linked@example.com")
        unlinked_tenant = await make_tenant_model(db, email="unlinked@example.com")

        response = await client.put(
            f"/api/v1/tenants/{unlinked_tenant.id}/link-user",
            json={"user_id": str(user.id)},
            headers=ctx.headers,
        )

        assert response.status_code == 409

    async def test_relinking_same_user_is_idempotent(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        user = await make_user_model(db, username="idempotent_user", email="idempotent_user@example.com")
        tenant = await make_tenant_model(db, user_id=user.id)

        response = await client.put(
            f"/api/v1/tenants/{tenant.id}/link-user",
            json={"user_id": str(user.id)},
            headers=ctx.headers,
        )

        assert response.status_code == 200
        assert response.json()["user_id"] == str(user.id)

    async def test_regular_user_cannot_link(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        tenant = await make_tenant_model(db)
        target_user = await make_user_model(db, username="target_user", email="target_user@example.com")

        response = await client.put(
            f"/api/v1/tenants/{tenant.id}/link-user",
            json={"user_id": str(target_user.id)},
            headers=ctx.headers,
        )

        assert response.status_code == 403


@pytest.mark.asyncio
class TestUnlinkTenantUserRoute:
    async def test_manager_can_unlink_tenant(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        user = await make_user_model(db, username="unlink_user", email="unlink_user@example.com")
        tenant = await make_tenant_model(db, user_id=user.id)

        response = await client.delete(
            f"/api/v1/tenants/{tenant.id}/link-user",
            headers=ctx.headers,
        )

        assert response.status_code == 200
        assert response.json()["user_id"] is None

    async def test_manager_cannot_unlink_another_managers_tenant(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr", email="othermgr@example.com", role=UserRole.MANAGER
        )
        user = await make_user_model(db, username="unlink_user", email="unlink_user@example.com")
        tenant = await make_tenant_model(db, user_id=user.id)
        prop = await make_property_model(db, manager_id=other_manager.id)
        await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)

        response = await client.delete(
            f"/api/v1/tenants/{tenant.id}/link-user",
            headers=ctx.headers,
        )
        assert response.status_code == 403

    async def test_unlinking_already_unlinked_tenant_is_idempotent(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)

        response = await client.delete(
            f"/api/v1/tenants/{tenant.id}/link-user",
            headers=ctx.headers,
        )

        assert response.status_code == 200
        assert response.json()["user_id"] is None

    async def test_returns_404_when_tenant_not_found(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        response = await client.delete(
            f"/api/v1/tenants/{uuid.uuid4()}/link-user",
            headers=ctx.headers,
        )

        assert response.status_code == 404

    async def test_regular_user_cannot_unlink(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        user = await make_user_model(db, username="protected_user", email="protected_user@example.com")
        tenant = await make_tenant_model(db, user_id=user.id)

        response = await client.delete(
            f"/api/v1/tenants/{tenant.id}/link-user",
            headers=ctx.headers,
        )

        assert response.status_code == 403

    async def test_unlinked_tenant_can_be_relinked_to_a_new_user(self, client, db, authenticate_manager):
        """End-to-end check that unlink genuinely frees up the tenant slot
        rather than leaving a stale link the unique constraint would reject."""
        ctx = await authenticate_manager()
        old_user = await make_user_model(db, username="old_user", email="old_user@example.com")
        new_user = await make_user_model(db, username="new_user", email="new_user@example.com")
        tenant = await make_tenant_model(db, user_id=old_user.id)

        await client.delete(f"/api/v1/tenants/{tenant.id}/link-user", headers=ctx.headers)

        response = await client.put(
            f"/api/v1/tenants/{tenant.id}/link-user",
            json={"user_id": str(new_user.id)},
            headers=ctx.headers,
        )

        assert response.status_code == 200
        assert response.json()["user_id"] == str(new_user.id)
