# Backend Architecture Decision Records

Use this directory for significant backend decisions that deserve a durable record.

High-value candidates from the current roadmap/history include:

- Contract vs Lease separation
- payment correction / immutability model
- audit-log write strategy: explicit service-layer calls vs. ORM event hooks
- receipt immutability
- transaction ownership
- PostgreSQL + MinIO consistency strategy
- storage key design
- capability-based module restructuring
- OpenAPI-derived frontend contracts
