# PropNest Backend — Database and Persistence

## 9. Database Architecture

The backend uses:

```text
PostgreSQL
    +
SQLAlchemy 2.x
    +
asyncpg
```

The database engine is asynchronous.

The application uses an asynchronous session factory.

The current backend development also adopted `NullPool` for the async engine in order to avoid connection-pooling issues encountered in the local/test architecture.

The exact production pooling strategy should remain environment-specific.

---


## 10. Async Session Design

The database session is injected into request processing.

Conceptually:

```text
Request
  |
  v
get_db()
  |
  v
AsyncSession
  |
  +--> service
        |
        +--> repository
```

The backend should have one clear owner for transaction boundaries.

A previously identified design concern is that `get_db()` committed after yielding while service methods also explicitly committed.

That produces a dangerous dual-commit model:

```text
service commits
    +
dependency commits
```

The recommended architectural invariant is:

> Transaction boundaries should be explicit and owned by the application layer that knows the business transaction.

For most request operations, that generally means the service/use-case layer rather than the raw DB dependency.

---


## 11. Transaction Design

A database transaction is not equivalent to a distributed transaction.

This is especially important for documents.

For a normal database-only operation:

```text
begin
  |
  +-- repository changes
  |
commit
```

For database + MinIO:

```text
database
   +
MinIO
```

there is no inherent atomic commit across both systems.

This creates failure modes such as:

### Case A

```text
DELETE DB row
DELETE MinIO object
COMMIT DB
```

If MinIO deletion succeeds but DB commit fails:

```text
object is gone
row comes back
```

### Case B

Reverse the order and the inverse inconsistency can occur.

Therefore document/file operations require explicit failure-compensation or an architecture that tolerates eventual consistency.

---


## 18. Repository Base Architecture

The backend uses a common repository abstraction with query-building behavior.

A base repository is intended to centralize repeated persistence mechanics.

The architectural rule should be:

```text
BaseRepository
    |
    +-- query construction
    +-- standard CRUD
    +-- common pagination
```

Entity-specific repositories should add domain-specific persistence methods only when necessary.

A repository method should not silently accept arguments it cannot propagate correctly.

A previously identified bug demonstrated this risk when `skip` was forwarded into a query builder that expected a different pagination argument.

Repository APIs should therefore have explicit typed signatures.

---


## 22. Configuration Architecture

The project moved away from direct `.env` access toward a centralized configuration object/dataclass.

This improves:

- type safety
- explicit defaults
- environment selection
- test configuration
- maintainability

Configuration should be resolved once and injected/consumed consistently.

---


## 23. Migrations

Alembic is the schema migration mechanism.

Migration design should follow:

```text
Model change
    |
    v
Alembic revision
    |
    v
upgrade()
    |
    v
PostgreSQL schema
```

Migrations must be treated as production artifacts.

A model change without a corresponding migration is incomplete.

---

