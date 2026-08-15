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

### Audit Logs

Create an audit trail for mutations.

The roadmap specifies:

- actor
- action
- entity type
- entity ID
- JSON diff
- timestamp

Audit rows should be part of the same database transaction as the mutation.

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

An administrative audit viewer may be introduced once the backend query endpoint exists.

The UI should support:

- filters
- entity/action context
- actor
- timestamp
- before/after diff where available

## Exit criteria

Phase 1 is complete when the backend modules are implemented, tested, and exposed through stable API contracts that can support Phase 2.

Status: Collections and Payments completion are done. Notifications abstraction and Audit Logs remain outstanding.

Frontend work in Phase 1 should remain minimal unless required to exercise or validate these capabilities.
