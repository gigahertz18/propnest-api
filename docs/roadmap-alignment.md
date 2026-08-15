# PropNest Backend — Roadmap Alignment

The supplied issues are the primary backend roadmap.

## Phase 1

Foundation modules:

- Collections — done
- completed Payments — done
- Notifications abstraction — outstanding
- Audit Logs — done

Important architectural consequence:

Audit logging should be transactionally coupled to mutations, and Notifications should expose a provider-independent interface.

## Phase 2

### Lease

Introduce long-term-specific billing terms without overloading neutral `Contract`.

### Billing

Make recurring long-term billing explicit and idempotent.

### Payment ↔ Billing

Reconcile payments against individual billing records and support partial/full/overpayment semantics.

### Receipts

Introduce append-only receipt generation and immutable PDF storage.

### Dashboard

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

The roadmap proposes eventually moving from:

```text
models/
repositories/
schemas/
services/
```

toward capability packages.

The most important decision is not the exact folder name; it is whether module ownership maps to business capabilities and keeps related tests/routes/models/services together.

## Backend design rule

Do not let the roadmap force implementation of future abstractions prematurely.

The issue set itself explicitly defers detailed design for far-future areas such as Leasing, Accounting, Mosaic AI, and integrations.
