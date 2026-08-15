# PropNest — Responsibility Matrix

| Capability | Backend responsibility | Frontend responsibility |
|---|---|---|
| Authentication | JWT, session identity, credential validation | Login/logout UI, session state |
| Authorization | Authoritative role/resource enforcement | Navigation and UX gating |
| Properties | Persistence and property rules | Property CRUD and presentation |
| Documents | Metadata, storage, access policy | Upload/list/download/delete UX |
| Collections | Grouping model and rules | Collection management UX |
| Payments | Financial record semantics and state | Payment entry/history/status |
| Audit Logs | Transactional audit-write mechanism, entity/actor query filtering | Admin audit viewer |
| Billing | Recurring charge generation and state machine | Billing view/status/payment application |
| Receipts | Numbering, PDF generation, immutable storage | View/download/reprint |
| Dashboard | Aggregations and authoritative metrics | Dashboard presentation |
| Owner Portal | Scoped permissions and data access | Read-only owner experience |
| Tenant Portal | Tenant-scoped authorization/data | Tenant experience |
| Maintenance | Ticket workflow and cost data | Ticketing UX and attachments |
| Leasing | Workflow/state and domain rules | Listing/leasing workflow |
| Agent | Agent permissions and commission rules | Agent workspace |
| Accounting | Financial aggregations/reporting data | Reports and visualization |
| AI | Read-only query service and policy | Query interface and results |
| Integrations | Provider adapters and credentials | Configuration/status UX |

## Principle

The frontend may make a feature easy to use, but the backend remains responsible for deciding whether an operation is valid and authorized.
