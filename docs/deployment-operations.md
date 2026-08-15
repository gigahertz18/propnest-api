# PropNest Backend — Deployment and Operations

## 33. Deployment Architecture

The current development system uses Docker Compose around services such as:

```text
Frontend
Backend
PostgreSQL
MinIO
```

Conceptually:

```text
                   ┌─────────────────┐
                   │     Browser     │
                   └────────┬────────┘
                            │
                            v
                   ┌─────────────────┐
                   │ Next.js Web App │
                   └────────┬────────┘
                            │
                            v
                   ┌─────────────────┐
                   │    FastAPI      │
                   └──────┬───┬──────┘
                          │   │
              ┌───────────┘   └─────────────┐
              v                             v
       ┌──────────────┐              ┌──────────────┐
       │  PostgreSQL  │              │    MinIO     │
       └──────────────┘              └──────────────┘
```

---


## 21. Seed / Administrative Operations

The project includes administrative seed/setup tooling such as the admin seed script.

These scripts should use the same async database architecture as the application.

A previous issue was an obsolete synchronous `SessionLocal` import in `scripts/seed_admin.py` after the migration to `AsyncSessionLocal`.

The architectural rule is:

> Operational scripts must use the same session abstractions as application code unless there is a deliberate reason to use another database access mechanism.

---


## 32. Observability

The backend uses application logging, but excessive SQLAlchemy/database logging had previously made test output noisy.

The desired logging hierarchy is:

```text
application
    |
    +-- service events
    +-- authorization failures
    +-- external-storage failures
    +-- database failures
```

Infrastructure debug logging should be configurable by environment.

Sensitive information such as:

- passwords
- access tokens
- raw authorization headers

must never be logged.

---


## 30. Performance Considerations

The main backend performance risks are currently architectural rather than algorithmic.

### 30.1 N+1 queries

Care should be taken when serializing relationships for list endpoints.

### 30.2 Count queries

Pagination requires a count query, which should be designed carefully for large tables.

### 30.3 Storage listing

Document/image endpoints should avoid repeatedly downloading or scanning unnecessary data.

### 30.4 Connection usage

Async sessions and production connection-pool configuration should be monitored under load.

### 30.5 Large file handling

Files should stream through request/storage pipelines where practical rather than being unnecessarily loaded into memory.

---

