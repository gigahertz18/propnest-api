"""
Fake repositories for ResourceAuthorizationMixin-based service unit tests
(`DocumentService`, `ContractService`, and any future one).

Lives at the same level as `factories.py` rather than nested under
`tests/unittests/services/` or `tests/fixtures/` — like `factories.py`,
this is a plain importable module with no `@pytest.fixture` decorators
and no `pytest_plugins` registration, so it belongs alongside it rather
than alongside `tests/fixtures/auth.py`'s actual pytest fixtures.

For the User-shaped test doubles these tests also need (`make_admin`,
`make_manager`), see `tests/factories.py` — they're lightweight cousins
of `make_admin_model` there, not repos, so they don't belong in this file.

Two repo shapes cover everything these services need:

- `FakeReadOnlyRepo` — stands in for a *related* resource repo (Property,
  Contract, or Tenant, whenever the test is treating it as something the
  service under test only needs to look up, not own). Every related-repo
  need in this codebase is the same one method: `get_by_id`.

- `FakeCRUDRepo` — stands in for a service's *own* primary repo (e.g.
  ContractService's `contract_repo`, DocumentService's `document_repo`).
  It doesn't know any entity's field names: `create`/`update` just mirror
  whatever a Pydantic payload has (`payload.model_dump()`) onto a
  `SimpleNamespace`, so the same class works for Document and Contract
  payloads without a subclass — new entities only need to subclass this
  if they have query methods beyond get_all/get_by_id/create/update/delete
  (e.g. Contract's `get_by_property`, `get_by_status`, etc.).
"""

from types import SimpleNamespace
from uuid import uuid4


class MockReadOnlyRepo:
    """Generic stand-in for a related-resource repo — used wherever a test
    only needs `get_by_id` (Property, Contract, or Tenant, when playing
    the role of something looked up rather than owned)."""

    def __init__(self, records: dict | None = None):
        self.records = records or {}

    async def get_by_id(self, db, id):
        return self.records.get(id)


class MockCRUDRepo:
    """Generic stand-in for an entity's own primary repo.

    Tracks every operation (`created_payloads`, `updated_payloads`,
    `deleted_ids`) so tests can assert not only on the outcome but also on
    whether the repo was called at all — the key signal that
    validation/authorization ran *before* any DB write was attempted.
    """

    def __init__(self, records: dict | None = None):
        self.records = dict(records or {})
        self.created_payloads: list = []
        self.updated_payloads: list = []
        self.deleted_ids: list = []

    async def get_all(self, db, skip=0, limit=100):
        return list(self.records.values())[skip : skip + limit]

    async def get_by_id(self, db, id):
        return self.records.get(id)

    async def create(self, db, payload):
        self.created_payloads.append(payload)
        obj = SimpleNamespace(id=uuid4(), **payload.model_dump())
        self.records[obj.id] = obj
        return obj

    async def update(self, db, id, payload):
        if id not in self.records:
            return None
        self.updated_payloads.append((id, payload))
        obj = self.records[id]
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        return obj

    async def delete(self, db, id):
        if id not in self.records:
            return None
        self.deleted_ids.append(id)
        return self.records.pop(id)

    async def _filter_by(self, **filters) -> list:
        """Helper for subclasses adding entity-specific `get_by_*` query
        methods — not part of any real repo's interface."""
        return [
            record
            for record in self.records.values()
            if all(getattr(record, field, None) == value for field, value in filters.items())
        ]
