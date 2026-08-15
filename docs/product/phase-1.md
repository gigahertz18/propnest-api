# PropNest — Phase 1

## Goal

Complete the foundation required before the core recurring-rent workflow is built.

## Backend scope from the roadmap

### Collections — done

The organizational grouping layer for documents is implemented.

Resolved design questions:
- Collections group Documents only (not generalized entity references) — the roadmap's own framing scoped this to documents for the first pass
- a Collection belongs to exactly one Property (required), optionally narrowed to one of that property's Contracts
- grouping is optional: `Document.collection_id` is a nullable FK (`ON DELETE SET NULL`)

### Payments completion — done

Payment semantics are complete:

- `reference_number`
- `check` payment method
- real payment status lifecycle: `PAID`, `PENDING`, `VOIDED`, `REFUNDED`
- explicit correction strategy (append-only: void the original, create a new payment row referencing it) that preserves payment history

### Notifications abstraction

Introduce:

- `NotificationChannel`
- `NotificationService`
- local no-op/logging implementation
- extension points for future email/SMS/push/Messenger/WhatsApp providers

### Audit Logs — done

An `AuditLog` model and a shared `write_audit_log()` helper are implemented, matching the roadmap's shape:

- actor (`actor_id`, nullable FK to `users.id`, `ON DELETE SET NULL` — a deleted account never blocks or erases the trail)
- action (`CREATE` / `UPDATE` / `DELETE`)
- entity type / entity ID (polymorphic — no FK, since one column can't reference every mutable table)
- JSON diff (nullable)
- timestamp (`created_at` only — audit rows are immutable, no `updated_at`)

Every mutating method across all six existing services (Property, Contract, Tenant, Document, Payment, User) calls `write_audit_log()` immediately before its own `db.commit()`, so the audit row is part of the same transaction as the underlying change — a rolled-back mutation never leaves an orphaned audit row. This is deliberately an explicit per-call-site pattern rather than SQLAlchemy ORM event hooks, consistent with how this codebase already handles authorization and existence-checking explicitly rather than via hooks.

Read access is exposed via `GET /api/v1/audit-logs`, admin-only, filterable by `entity_type`/`entity_id`, paginated like every other list endpoint.

## Frontend implications

The supplied roadmap does not contain frontend issues, so the following is **planned frontend scope derived from the backend capabilities**.

### Collections — planned

The backend domain model is now finalized (see above); the frontend work itself is still planned. Provide a way to:

- view document collections
- create/rename collections
- add/remove documents from a collection
- see collection membership from property/contract/tenant contexts

### Payments — planned

Prepare admin/manager payment workflows to display:

- payment reference number
- method
- lifecycle status
- correction/reversal history

The UI must not imply that a historical payment can be silently edited once the backend adopts immutable correction semantics.

### Notifications — foundation only

No end-user notification UI is required merely to introduce the backend abstraction.

Later UI should consume notifications through a stable API rather than depending on provider-specific behavior.

### Audit Logs — planned

The backend query endpoint (`GET /api/v1/audit-logs`) now exists; an administrative audit viewer consuming it is still planned frontend work.

The UI should support:

- filters
- entity/action context
- actor
- timestamp
- before/after diff where available

## Exit criteria

Phase 1 is complete when the backend modules are implemented, tested, and exposed through stable API contracts that can support Phase 2.

Status: Collections, Payments completion, and Audit Logs are done. Notifications abstraction remains outstanding.

Frontend work in Phase 1 should remain minimal unless required to exercise or validate these capabilities.
