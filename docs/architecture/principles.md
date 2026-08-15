# PropNest — Architecture Principles

1. **Backend authority** — the backend is the source of truth for authorization and domain rules.
2. **Layered backend** — routes delegate to services; services coordinate repositories and external systems.
3. **Secure frontend boundary** — browser code calls same-origin Next.js APIs rather than FastAPI directly.
4. **Explicit transactions** — transaction ownership is explicit; PostgreSQL transactions do not implicitly include MinIO operations.
5. **Typed contracts** — API request and response shapes are modeled explicitly.
6. **Test isolation** — unit and integration tests isolate dependencies appropriately and must never accidentally use unsafe databases.
7. **No premature abstraction** — introduce shared infrastructure when complexity justifies it.
8. **Documentation follows architecture** — architectural changes should update the relevant document in the same change.
