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

### Lease — done

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

A Lease must only attach to a long-term Contract, enforced by `LeaseService` (not a DB constraint).

### Recurring Billing — done (generation + overdue evaluation)

Build the monthly billing engine around active long-term leases.

Delivered:

- billing state machine — a record starts `pending` (set at generation), and from there can move to `overdue` (grace period elapsed unpaid), `partially_paid`, or `paid`; `overdue`/`partially_paid` can each transition to the other, to `paid`, or to `written_off`; `paid`/`written_off` are terminal — enforced via an explicit transition table (there is no separate `generated` status; `pending` *is* the freshly-generated state)
- periods are server-computed and always contiguous — `period_start` is `lease.start_date` for a lease's first record, otherwise the previous record's `period_end + 1 day`; a caller only supplies `lease_id`, never a period, so a lease can never be billed for days before it started or left with an unbilled gap between periods
- idempotent generation, guarded by a DB uniqueness constraint on lease + billing period, covering the case of two concurrent requests computing the same next period before either commits
- late-fee handling on crossing into overdue, per the lease's grace period and late-fee terms
- generation and overdue evaluation now also run automatically via daily `arq` cron jobs (`app/jobs/billing_jobs.py`) against a `system.scheduler` identity, on top of the existing manual `POST /billing-records/generate` / `/evaluate-overdue` endpoints kept for on-demand/backfill use — both paths call the same idempotent `LeaseBillingService` methods

#### Verifying the scheduler manually

There's no live-Redis integration test exercising the cron schedule end-to-end — the unit tests
in `tests/unittests/jobs/test_billing_jobs.py` cover the job functions' logic directly, and this
manual check is the accepted fallback for confirming the schedule itself fires:

- Start the stack with `make up-detached`; the `worker` service (arq, `app.jobs.billing_jobs.WorkerSettings`) starts alongside `backend`, sharing the same Postgres/Redis.
- Tail its logs with `make logs-worker` — each run logs `billing_jobs.generate_due_billing_records: generated=%d skipped=%d` and `billing_jobs.evaluate_overdue_billing_records: evaluated=%d`.
- To see a run sooner than the default 01:00 schedule, set `BILLING_JOB_CRON_HOUR`/`BILLING_JOB_CRON_MINUTE` to a time a few minutes out and restart the `worker` service, or exec into it (`make shell-be`-style `docker compose -f docker/docker-compose.yml exec worker sh`) and invoke `generate_due_billing_records`/`evaluate_overdue_billing_records` directly for a one-off check.
- Confirm the effect via existing tooling — `GET /billing-records/?lease_id=` for a known lease should show a newly generated record, or `make shell-db` to inspect `billing_records` directly.

### Payments ↔ Billing — done

Payment recording updates the associated billing record based on cumulative payment
state:

- `Payment.billing_record_id` — nullable, additive to `contract_id` (a payment can
  optionally link to a specific `BillingRecord`; the contract-only flow still works
  unchanged for payments that don't).
- `PaymentService.create_payment` validates the referenced billing record belongs to
  the same contract (via its Lease) before recording the payment.
- `LeaseBillingService.apply_payment` recomputes the record's status from the sum of
  its non-voided payments against `amount_due + late_fee_amount_charged`, transitioning
  to `partially_paid`/`paid` per the existing state machine.
- Overpayment isn't rejected: the record still resolves to `paid`, with the excess
  tracked on `BillingRecord.overpaid_amount` for later Dashboard/Accounting use.

### Immutable Receipts — done

Generate sequential receipts as PDFs.

Receipt requirements:

- immutable stored document
- receipt number
- payment relationship
- MinIO-backed document storage
- reprint without overwriting the original receipt

### Landlord Dashboard — done

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

Done (see `propnest-web/docs/product/phase-2.md` for the frontend-side detail):

- generate the next billing record(s) for a lease — a "periods to generate" count, not a
  caller-picked period/date, since `propnest-api` now computes `period_start` itself
- re-evaluate/refresh a billing record's overdue status and balance on demand
- billing records for a lease (persisted list/history, via `GET /billing-records/?lease_id=`)
- current-period balance
- payment state
- overdue state
- partial-payment state

Planned:

- payment history (per billing record, surfaced alongside the lease's billing history)

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
