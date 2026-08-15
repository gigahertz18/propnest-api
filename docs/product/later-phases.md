# PropNest — Later Phases

The supplied roadmap places the following capabilities after the internal alpha.

## Owner Portal

Read-only, property-scoped access for owners.

Backend requirements:
- owner role
- property-level scope
- contracts
- receipts
- payments
- income reports
- occupancy

Frontend implications:
- dedicated owner experience
- property-scoped navigation
- read-only UI
- contract/payment/receipt/report views

## Tenant Portal

Tenant-scoped access to:

- lease
- receipts
- payment history
- maintenance
- announcements

Frontend should reuse the scoped-access pattern proved by the Owner Portal.

## Maintenance

Workflow:

```text
Issue
  -> Assign
  -> Repair
  -> Cost
  -> Complete
```

Frontend implications:
- ticket list/detail
- assignment/status workflow
- photos
- invoice attachments
- tenant-visible status

## Leasing

Workflow:

```text
Vacant
  -> Listing
  -> Inquiry
  -> Viewing
  -> Reservation
  -> Application
  -> Approval
  -> Lease
```

The roadmap explicitly says this should be split into smaller issues when the phase is actually started.

## Agent Portal

Agent capabilities:

- listings
- leads
- viewings
- applications
- commissions

It should reuse scoped-permission patterns rather than introduce an unrelated access model.

## Landlord Accounting

Views for:

- income
- expenses
- profit
- cash flow
- security deposits
- refunds
- tax reports

The supplied issue explicitly says this is not intended to be a QuickBooks replacement.

## Mosaic AI

Read-only natural-language queries over structured PropNest data.

Examples from the roadmap include questions about:
- late-payment patterns
- expiring leases
- maintenance costs
- property income

No write/automation capability is planned in the supplied issue.

## Third-party integrations

The roadmap lists:

- GCash
- Maya
- Xero
- QuickBooks
- Google Calendar
- Outlook
- Drive/Dropbox
- SMS gateway

These are intentionally delayed until there are active non-family users.

The frontend should treat providers as adapters behind stable application capabilities rather than provider-specific UI.
