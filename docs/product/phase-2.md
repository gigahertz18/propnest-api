# PropNest — Phase 2

## Goal

Build the core long-term rental management loop.

## Dependency chain

```text
Contract
   |
   v
Lease
   |
   v
Billing Record
   |
   v
Payment
   |
   v
Receipt
   |
   v
Dashboard
```

## Backend scope

### Lease

A dedicated 1:1 `Lease` record attaches long-term-specific billing terms to a neutral `Contract`.

Important fields include:

- monthly rent
- due day
- billing cycle
- security deposit
- advance payment
- late-fee definition
- grace period
- renewal option
- lease status
- start/end dates

A Lease must only attach to a long-term Contract.

### Recurring Billing

Build the monthly billing engine around active long-term leases.

Important requirements:

- billing state machine
- idempotent generation
- late-fee handling
- manual trigger initially
- explicit link between Payment and Billing Record
- support for partial/full/overpayment cases

### Payments ↔ Billing

Payment recording must update the associated billing record based on cumulative payment state.

### Immutable Receipts

Generate sequential receipts as PDFs.

Receipt requirements:

- immutable stored document
- receipt number
- payment relationship
- MinIO-backed document storage
- reprint without overwriting the original receipt

### Landlord Dashboard

Expose read-only aggregation data:

- Collected This Month
- Outstanding
- Late Payments
- Vacant Units
- Expiring Leases
- Recent Payments

## Frontend scope derived from Phase 2

The frontend must turn the backend operational loop into a usable landlord/manager workflow.

### Dashboard

The existing dashboard should evolve into the operational dashboard defined by the backend roadmap.

Planned sections:

```text
Collected This Month
Outstanding
Late Payments
Vacant Units
Expiring Leases
Recent Payments
```

Each metric should be independently loadable and testable.

### Lease Management

Planned UI:

- lease list
- lease detail
- create lease
- edit lease
- lease status
- rent/billing terms
- due day and grace period
- lease dates

Creation should clearly identify that a Lease is available only for long-term Contracts.

### Billing

Planned UI:

- billing records for a lease
- current-period balance
- payment state
- overdue state
- partial-payment state
- payment history

The frontend should display the billing state machine rather than inventing its own status semantics.

### Payment Recording

Planned UI:

- record payment
- payment method
- reference number
- applied billing record
- amount
- payment status
- partial/full/overpayment result

### Receipts

Planned UI:

- view receipt
- download receipt PDF
- list receipt history
- reprint without mutating the original receipt

### Alpha readiness

The frontend should be considered Phase 2-complete only when the actual end-to-end workflow can be performed without backend-only tooling:

```text
Property
  -> Contract
  -> Lease
  -> Monthly Billing
  -> Payment
  -> Receipt
  -> Dashboard
```

## Exit criteria

Phase 2 is complete when the core rental lifecycle is usable end-to-end, CI passes, and the system is ready for the internal alpha.
