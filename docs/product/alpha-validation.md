# PropNest — Internal Alpha Validation

## Purpose

The internal alpha is the product validation gate after Phase 2.

It is explicitly intended to reveal problems that cannot be predicted reliably through design and automated tests alone.

## Scope

Use PropNest exclusively for the family's actual rental properties for **2–3 months**.

The roadmap explicitly says:

> No major new features during this window.

The objective is validation, not continued feature expansion.

## What to observe

### Billing behavior

Capture:

- partial months
- late payments
- grace-period edge cases
- late-fee disputes
- corrections
- overpayments
- underpayments

### Receipt behavior

Capture:

- mistaken payment entries
- reprints
- receipt numbering issues
- document retrieval problems

### Operational friction

Capture:

- confusing screens
- repetitive workflows
- missing information
- slow operations
- unnecessary clicks
- data-entry errors

### Data quality

Validate:

- property data
- tenant data
- contract/lease data
- payment history
- billing records
- receipts

## Issue policy

Problems discovered during alpha should become separate issues.

Do not silently expand Phase 2 or add major feature scope in the middle of the validation window.

## Exit criteria

The alpha ends when:

1. the 2–3 month window is complete;
2. real-world billing and receipt edge cases have been collected;
3. the resulting issue set has been reviewed;
4. Phase 3+ priorities have been re-evaluated against observed usage.

## Frontend-specific alpha evaluation

Pay particular attention to:

- whether the dashboard answers the landlord's daily questions quickly
- whether payment recording matches real-world workflows
- whether billing states are understandable
- whether receipt retrieval/reprinting is obvious
- whether users can recover from mistakes without destructive edits
- whether mobile/responsive use is adequate for operational tasks
