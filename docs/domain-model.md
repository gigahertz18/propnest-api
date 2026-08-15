# PropNest Backend — Domain Model and Feature Boundaries

## 8. Property Ownership Model

Properties support manager assignment through `manager_id`.

This relationship is important because managers should generally operate on properties within their ownership/management scope.

A manager-aware service operation therefore follows a pattern like:

```text
current user
    |
    v
authorization check
    |
    +-- admin -> allowed
    |
    +-- manager -> allowed only for managed property
    |
    +-- user -> denied
```

A significant design issue previously identified is that property creation/update request schemas did not expose manager assignment even though the model and response represented `manager_id`.

That creates an architectural mismatch:

```text
Model supports manager assignment
        but
Request contract does not establish assignment
        therefore
Ownership is difficult to establish through the public API
```

This should be resolved deliberately rather than through test-only factories.

---


## 27. Tenant/User Boundary

A recurring domain question is the distinction between:

```text
User
```

and:

```text
Tenant
```

These should not be conflated.

A `User` represents an authenticated application principal.

A `Tenant` represents a business/domain party occupying/renting a property.

They may eventually be related through accounts, invitations, or portal access, but the domain concepts should remain separate.

This distinction becomes increasingly important when lease and tenant workflows become richer.

---


## 28. Contract / Lease Domain

Contracts/leases are a core property-management domain entity.

The intended architecture is:

```text
Contract Route
    |
    v
Contract Service
    |
    v
Contract Repository
    |
    v
Contract Model
```

The service layer should own rules such as:

- related property/tenant existence
- authorization
- lease state transitions
- date consistency
- ownership/scope

Foreign-key errors encountered during tests illustrate why fixture creation must respect domain dependency order:

```text
property
   |
   +--> tenant
   |
   +--> contract
```

---


## 26. Payments

Payments is a fully implemented vertical slice: model, schema, repository, service, and routes all exist and are tested end-to-end.

The `Payment` model supports:

- `reference_number` (nullable) — cross-references the transaction on the provider side (bank transfer/GCash/Maya/check)
- `payment_method` including `check` alongside cash/bank transfer/gcash/maya
- a real `PaymentStatus` lifecycle: `PAID`, `PENDING`, `VOIDED`, `REFUNDED`

Corrections use an append-only model rather than in-place mutation, since a receipt may already reference a payment's id:

```text
POST /payments/{id}/corrections
    |
    v
PaymentService.void_and_correct_payment
    |
    +--> original payment marked VOIDED
    |
    +--> new payment row created, corrects_payment_id -> original
```

A direct `PATCH` to `status=VOIDED` is rejected (422) — voiding only happens through the correction endpoint — and any update to an already-voided payment is rejected (409).

---


## 29. Collections

`Collection` is the organizational grouping layer for Documents, added after the initial per-entity modules.

A Collection belongs to exactly one Property (required `property_id`) and may optionally narrow to one of that property's Contracts (`contract_id`, validated to belong to the same property). This mirrors how every other entity in this codebase resolves its authorization anchor through Property.

```text
Property (required)
    |
    +--> Collection --> optional Contract (same property)
              |
              v
         Document.collection_id (nullable, ON DELETE SET NULL)
```

A `Document` may optionally belong to one Collection via a nullable `collection_id` FK. Deleting a Collection does not delete its documents — the FK is `SET NULL`, not cascading — since a document's existence shouldn't depend on the grouping placed on top of it.

CRUD + manager-scoped listing exist at `/api/v1/collections`, following the same repository/service/route shape as Tenant/Contract.

---


## 30. Audit Logs

`AuditLog` records every mutation across the six existing services (Property, Contract, Tenant, Document, Payment, User) — one row per create/update/delete.

```text
id
actor_id      (nullable FK -> users.id, ON DELETE SET NULL)
action        (CREATE / UPDATE / DELETE)
entity_type   (polymorphic — no FK, since one column can't reference every mutable table)
entity_id
diff          (nullable JSON)
created_at    (immutable — no updated_at)
```

Audit rows are written via a shared `write_audit_log()` helper, called explicitly by each mutating service method immediately before its own `db.commit()` — a deliberate choice over SQLAlchemy `after_insert`/`after_update`/`after_delete` ORM event hooks, since hooks would be invisible at the call site and inconsistent with how authorization and existence-checking are already handled explicitly elsewhere in the service layer. Because the write shares the same session/transaction as the underlying change, a rolled-back mutation never leaves an orphaned audit row.

`GET /api/v1/audit-logs` exposes read access: admin-only, filterable by `entity_type`/`entity_id`, paginated like every other list endpoint.

---


## 12. Document Architecture

Documents are both:

1. database metadata
2. object storage content

A document record contains metadata such as:

- document ID
- property/contract/tenant relationship
- optional collection relationship (`collection_id`)
- file name
- document type
- file URL/storage reference
- timestamps

The actual file content is stored in MinIO.

---

