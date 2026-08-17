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

### Billing — done (generation + overdue evaluation; manual trigger only)

Make recurring long-term billing explicit and idempotent.

### Payment ↔ Billing — done

Reconcile payments against individual billing records and support partial/full/overpayment semantics.

### Receipts — done

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
