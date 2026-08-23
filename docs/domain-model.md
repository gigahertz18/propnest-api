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
- `billing_record_id` (nullable) — additive to the required `contract_id`, not a replacement; a payment may optionally link to a specific `BillingRecord`. `PaymentService.create_payment` validates the billing record belongs to the same contract (via its Lease) before recording, then reconciles cumulative non-voided payments into the record's status via `LeaseBillingService.apply_payment` (see §31)

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


## 31. Billing Records

`BillingRecord` is the recurring-billing engine for long-term leases: one row per `Lease` per billing period, generated by `LeaseBillingService` — either on-demand via the manual endpoints or automatically via a daily `arq` cron job (`app/jobs/billing_jobs.py`).

```text
LeaseBillingService.generate_billing_record
    |
    +--> period_start computed server-side: lease.start_date for the lease's
    |    first record, otherwise (previous record's period_end + 1 day) —
    |    never taken from the caller, so periods are always contiguous and
    |    can never precede the lease's actual start
    |
    +--> BillingRecord created and left in status = pending
    |
    +--> unique (lease_id, period_start) constraint catches the case where two
         concurrent requests both computed the same next period before either
         committed — a normal repeated call just advances to the next period
```

The model tracks:

- `period_start` — server-computed (see above), not caller-supplied
- `period_end` — `period_start + 30 days` for the (only) `monthly` billing cycle, not calendar-month-aligned
- `due_date` — `period_start + Lease.due_day days`; `due_day` is a day-offset from `period_start`, not a calendar day-of-month, and nothing is clamped
- `amount_due` — a snapshot of `Lease.monthly_rent` at generation time, so a later rent change doesn't rewrite billing history
- `late_fee_applied` / `late_fee_amount_charged` — set once `LeaseBillingService.evaluate_overdue` determines the record has passed `due_date + Lease.grace_period_days`, computed from whichever of `Lease.late_fee_amount`/`late_fee_percent` is set
- `overpaid_amount` (nullable) — set by `LeaseBillingService.apply_payment` when cumulative non-voided payments exceed `amount_due + late_fee_amount_charged`; the record still resolves to `paid` rather than rejecting the payment. Consumed by the Dashboard's separate `total_credits` figure (`BillingRecordRepository.sum_credits`/`sum_credits_for_manager`) — deliberately not netted into `outstanding`, which still sums only `amount_due + late_fee_amount_charged` on non-terminal records. A future Accounting module remains the natural home for any richer reconciliation between the two.

Status is a native-enum state machine — a freshly generated record starts `pending`, then moves to `partially_paid`, `paid`, or `overdue`; `partially_paid`/`overdue` can each still reach `paid` or `written_off` — with transitions validated against an explicit table in the service; an invalid transition raises rather than silently succeeding.

`BillingRecord` deliberately has no `payment_id`/`amount_paid` field — it doesn't track its own paid-to-date total. Instead, `Payment.billing_record_id` (nullable, see §26) links payments to it, and `PaymentService.create_payment` sums the linked non-voided payments and calls `LeaseBillingService.apply_payment` to reconcile that sum into this record's `status`/`overpaid_amount` — the `Payment ↔ Billing` roadmap item (see `roadmap-alignment.md`) is implemented. This is long-term-lease-specific by design, mirroring `Lease` itself: a future short-term booking-billing model is expected to be its own entity, not a `rental_type` branch grafted onto this one.

`POST /api/v1/billing-records/generate`, `POST /api/v1/billing-records/{id}/evaluate-overdue`, `POST /api/v1/billing-records/{id}/write-off`, `PATCH /api/v1/billing-records/{id}/late-fee`, `GET /api/v1/billing-records/?lease_id=...`, and `GET /api/v1/billing-records/{id}` are all manager-or-above gated, following the same ownership-scoping pattern as Lease (authorized via the lease's contract's property).

`write_off_billing_record` is the only route-exposed path to `written_off` (only reachable from `partially_paid`/`overdue`, per the transition table). `correct_late_fee` lets a manager-or-above correct `late_fee_applied`/`late_fee_amount_charged` — e.g. to reverse an erroneous overdue evaluation — but only while the record is still non-terminal; it's rejected once the record is `paid`/`written_off`.

---


## 32. Receipts

`Receipt` is the append-only issuance record for a payment's PDF receipt — the `receipt-engine-pdf-immutable` roadmap item (see `roadmap-alignment.md`) is implemented.

```text
POST /payments/{payment_id}/receipts
    |
    +--> ReceiptService.issue_receipt
             |
             +--> receipt_number allocated from a Postgres Identity sequence (nextval)
             |
             +--> template HTML resolved: property's active ReceiptTemplate, else the
             |    active global ReceiptTemplate, else the built-in default (see below)
             |
             +--> PDF rendered via Jinja2 + WeasyPrint (app/services/receipt_pdf.py)
             |
             +--> DocumentService.create_document stores the PDF (reuses the existing
             |    MinIO-backed Document pattern, linked via contract_id)
             |
             +--> Receipt row created: payment_id (FK, not unique) + document_id (FK, unique)
```

The model tracks:

- `receipt_number` — a Postgres `Identity` column (unique, indexed), not an app-level `max()+1` — race-safe under concurrent payment recording since Postgres allocates sequence values atomically outside row locks. A global sequence, not per-property/per-year, matching the roadmap's beta-scale simplification.
- `payment_id` (FK, **not** unique) — multiple `Receipt` rows may reference the same payment; that's the whole point of reprints.
- `document_id` (FK, **unique**) — each `Receipt` owns exactly one generated PDF `Document`; a reprint always renders and stores a brand-new `Document`, never re-links an existing one.

Reprinting a receipt is not a separate endpoint — calling `POST /payments/{payment_id}/receipts` again for the same payment is the reprint: it creates a new `Receipt` + new `Document` row, and never mutates or re-renders the original. `Receipt` has no update path (no `ReceiptUpdate` schema, no `PATCH` route) — it's immutable by construction, matching the append-only correction model already established for `Payment` (see §26).

Receipt issuance is decoupled from `PaymentService.create_payment`'s own transaction: `POST /payments/` calls `payment_service.create_payment` (which commits), then separately calls `receipt_service.issue_receipt` in the same request. If receipt issuance fails after the payment already committed, the payment response still succeeds — the failure is logged, and a client can retry by calling `POST /payments/{payment_id}/receipts` again.

### Receipt Templates

`ReceiptTemplate` lets an admin or property manager customize the HTML/CSS behind a receipt's PDF, per property, with a global fallback — instead of every receipt using one hardcoded layout.

```text
POST /receipt-templates/            (multipart: name, property_id?, file)
    |
    +--> ReceiptTemplateService.upload_template
             |
             +--> HTML stored directly via the MinIO client (NOT through DocumentService/
             |    the generic Document model — its MIME allowlist is sniffed from binary
             |    magic bytes with no equivalent signature for arbitrary HTML, and mixing
             |    print templates into the general Documents listing isn't desirable)
             |
             +--> ReceiptTemplate row created with is_active=false

POST /receipt-templates/{id}/activate
    |
    +--> deactivates whichever template was previously active in the same scope
    |    (that property, or the global default), then activates this one
```

- `property_id` (nullable FK) — `NULL` means the global default template; a specific property_id scopes it to that property only.
- `is_active` — at most one active row per scope, enforced by a partial unique index (`uq_active_receipt_template_scope`) on `COALESCE(property_id, <sentinel-uuid>)` filtered to `is_active = true` — a plain unique index on `property_id` can't cover the global case, since Postgres treats multiple `NULL`s as distinct.
- Managing a property-scoped template requires owning that property (or ADMIN); managing the global template is ADMIN-only.
- `ReceiptService.issue_receipt` resolves which template to render with: the payment's property's active template, falling back to the active global template, falling back to the built-in file at `templates/receipt/default.html` (a repo-root-level directory, alongside `alembic/`/`scripts/`/`docs/` — organized for future default templates beyond receipts) if neither exists yet.
- Templates use Jinja2 placeholders (`{{ receipt_number }}`, `{{ property_name }}`, `{{ tenant_name }}`, `{{ amount }}`, `{{ paid_at }}`, `{{ payment_method }}`, `{{ reference_number }}`), autoescaped. `render_receipt_pdf` renders through WeasyPrint with a locked-down `url_fetcher` that refuses any `http(s)`/`file`/`ftp` resource fetch — a manager-uploaded template can't be used for SSRF or local-file reads via an `<img src="...">`; only inline `data:` URIs (e.g. a base64 logo) work for embedded images.

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
