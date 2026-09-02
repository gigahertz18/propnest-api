# PropNest Backend — Roadmap Alignment

The supplied issues are the primary backend roadmap.

## Phase 1

Foundation modules:

- Collections — done
- completed Payments — done
- Notifications abstraction — done
- Audit Logs — done

Important architectural consequence:

Audit logging should be transactionally coupled to mutations, and Notifications should expose a provider-independent interface.

## Phase 2

### Lease — done

Introduce long-term-specific billing terms without overloading neutral `Contract`.

### Billing — done (generation + overdue evaluation; automated via daily `arq` cron jobs, manual endpoints retained for on-demand/backfill use)

Make recurring long-term billing explicit and idempotent.

### Payment ↔ Billing — done

Reconcile payments against individual billing records and support partial/full/overpayment semantics.

### Receipts — done

Introduce append-only receipt generation and immutable PDF storage.

### Dashboard — done

Expose independently testable read-only aggregation queries.

## Internal Alpha

No major backend feature expansion during the 2–3 month validation period.

Use production-like real data and capture operational edge cases as issues.

## Phase 3+

Capabilities from the supplied roadmap:

- Owner
- Tenant
- Maintenance
- Leasing
- Agent
- Accounting
- Mosaic AI
- Third-party integrations

## Capability-based restructure

Completed. The backend moved from:

```text
models/
repositories/
schemas/
services/
```

to per-entity capability packages (`app/identity/`, `app/properties/`, `app/crm/`, `app/leasing/`, `app/collections/`, `app/documents/`, `app/billing/`, `app/receipts/`, `app/reporting/`), each keeping its own tests/routes/models/services together, with `app/core/` holding shared cross-cutting infra. The old flat directories have been removed.

## Backend design rule

Do not let the roadmap force implementation of future abstractions prematurely.

The issue set itself explicitly defers detailed design for far-future areas such as Leasing, Accounting, Mosaic AI, and integrations.
