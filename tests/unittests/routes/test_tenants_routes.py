import uuid


class TestTenantsRoutes:
    def test_get_tenant_returns_404_when_not_found(self, client, set_override, simple_ns):
        from app.core.dependencies import get_tenant_service

        set_override(get_tenant_service, lambda: simple_ns(get_tenant=lambda db, id: None))

        response = client.get(f"/api/v1/tenants/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_tenants_direct_calls_cover_returns(self):
        """Directly call route functions to ensure return lines execute under full test run."""
        from app.api.v1.routes import tenants as tenants_module
        import datetime

        now = datetime.datetime.utcnow().isoformat()
        sample_id = str(uuid.uuid4())
        sample = {
            "id": sample_id,
            "full_name": "Alice",
            "email": "alice@example.com",
            "phone_number": "123456",
            "date_of_birth": "1990-01-01",
            "current_address": "123 Lane",
            "occupation": None,
            "notes": None,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        svc = __import__("types").SimpleNamespace(
            list_tenants=lambda db, skip, limit: [sample],
            get_tenant=lambda db, id: sample,
            create_tenant=lambda db, payload: sample,
            update_tenant=lambda db, id, payload: sample,
            delete_tenant=lambda db, id: True,
        )

        # call functions directly with the fake service to hit return paths
        res = tenants_module.list_tenants(skip=0, limit=10, db=None, tenant_service=svc)
        assert isinstance(res, list) and res[0]["id"] == sample_id

        res = tenants_module.get_tenant(sample_id, db=None, tenant_service=svc)
        assert res["id"] == sample_id

        payload = {
            "full_name": "Alice",
            "email": "alice@example.com",
            "phone_number": "123456",
            "date_of_birth": "1990-01-01",
            "current_address": "123 Lane",
        }
        res = tenants_module.create_tenant(payload, db=None, tenant_service=svc)
        assert res["id"] == sample_id

        res = tenants_module.update_tenant(sample_id, payload, db=None, tenant_service=svc)
        assert res["id"] == sample_id

        # delete returns None on success (204) when called directly
        res = tenants_module.delete_tenant(sample_id, db=None, tenant_service=svc)
        assert res is None

    def test_update_and_delete_tenant_not_found_returns_404(self, client, set_override, simple_ns):
        from app.core.dependencies import get_tenant_service

        set_override(
            get_tenant_service,
            lambda: simple_ns(update_tenant=lambda db, id, payload: None, delete_tenant=lambda db, id: None),
        )

        response = client.patch(f"/api/v1/tenants/{uuid.uuid4()}", json={})
        assert response.status_code == 404

        response = client.delete(f"/api/v1/tenants/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_tenants_success_paths(self, client, set_override, simple_ns):
        """Cover list/get/create/update/delete success branches for tenants routes."""
        import datetime

        now = datetime.datetime.utcnow().isoformat()
        sample_id = str(uuid.uuid4())
        sample = {
            "id": sample_id,
            "full_name": "Alice",
            "email": "alice@example.com",
            "phone_number": "123456",
            "date_of_birth": "1990-01-01",
            "current_address": "123 Lane",
            "occupation": None,
            "notes": None,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        svc = __import__("types").SimpleNamespace(
            list_tenants=lambda db, skip, limit: [sample],
            get_tenant=lambda db, id: sample,
            create_tenant=lambda db, payload: sample,
            update_tenant=lambda db, id, payload: sample,
            delete_tenant=lambda db, id: True,
        )

        from app.core.dependencies import get_tenant_service

        set_override(get_tenant_service, lambda: svc)

        # list
        r = client.get("/api/v1/tenants/")
        assert r.status_code == 200
        assert isinstance(r.json(), list) and r.json()[0]["id"] == sample_id

        # get
        r = client.get(f"/api/v1/tenants/{sample_id}")
        assert r.status_code == 200

        # create
        payload = {
            "full_name": "Alice",
            "email": "alice@example.com",
            "phone_number": "123456",
            "date_of_birth": "1990-01-01",
            "current_address": "123 Lane",
        }
        r = client.post("/api/v1/tenants/", json=payload)
        assert r.status_code == 201

        # update
        r = client.patch(f"/api/v1/tenants/{sample_id}", json={"full_name": "A"})
        assert r.status_code == 200

        # delete
        r = client.delete(f"/api/v1/tenants/{sample_id}")
        assert r.status_code == 204
