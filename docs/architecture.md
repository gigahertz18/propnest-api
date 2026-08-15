# PropNest Backend — Architecture

## 4. Logical Architecture

The intended request path is:

```text
HTTP Request
    |
    v
FastAPI Route
    |
    | dependencies / authentication
    v
Service
    |
    v
Repository
    |
    v
SQLAlchemy AsyncSession
    |
    v
PostgreSQL
```

For documents/files:

```text
Route
  |
  v
DocumentService
  |
  +--> DocumentRepository --> PostgreSQL
  |
  +--> Storage abstraction --> MinIO
```

This separation is fundamental to maintainability.

---


## 5. Layer Responsibilities

### 5.1 Routes

Routes are responsible for:

- HTTP method/path declaration
- dependency injection
- extracting request parameters/body
- selecting the service operation
- converting service results to schemas
- translating known domain/API errors into HTTP responses

Routes should not contain:

- complex business rules
- multi-step authorization logic
- direct repository orchestration
- storage transaction workflows
- persistence implementation details

---

### 5.2 Services

Services are the primary business-logic boundary.

A service is responsible for:

- domain validation beyond simple schema validation
- authorization rules that depend on business state
- orchestrating repositories
- managing domain workflows
- coordinating transaction-sensitive operations
- coordinating external side effects such as object storage

Examples established during development include:

```text
PropertyService
TenantService
ContractService
DocumentService
UserService
```

Services should express **why** an operation is allowed and **what business sequence** must occur.

---

### 5.3 Repositories

Repositories encapsulate persistence operations.

Typical responsibilities:

- select/query construction
- filtering
- pagination
- loading entities
- inserts
- updates
- deletes

The repository layer should avoid making business authorization decisions.

A repository knows how to retrieve a property.

A service decides whether the current user is allowed to update it.

---

### 5.4 Models

SQLAlchemy models represent the database persistence model.

Important domain entities include:

```text
User
Property
Tenant
Contract / Lease
Document
Collection
Payment
```

Models should describe persistence concerns:

- columns
- relationships
- constraints
- indexes
- enum/value representation

They should not become the primary location for application workflows.

---

### 5.5 Schemas

Pydantic schemas define API contracts.

They should distinguish:

- create payloads
- update payloads
- response models
- pagination envelopes
- authentication payloads

A particularly important design rule is that read-only server-managed fields should not accidentally become writable request fields.

For example, a property response may expose `manager_id` while creation/update schemas determine whether assignment is actually permitted.

---


## 29. Cross-Service Design

Services should coordinate related domain operations without allowing route handlers to become orchestration layers.

For example:

```text
DocumentService
    |
    +--> verify property access
    |
    +--> create/update document metadata
    |
    +--> coordinate storage
```

However, services should avoid excessive cross-service coupling.

When a workflow requires several aggregates, the orchestration boundary should be explicit.

---


## 38. Backend Request Lifecycle

A typical authenticated request should follow this sequence:

```text
HTTP request
    |
    v
FastAPI route
    |
    v
authentication dependency
    |
    v
current user
    |
    v
service method
    |
    +--> domain validation
    |
    +--> authorization
    |
    +--> repository
    |       |
    |       v
    |   AsyncSession
    |       |
    |       v
    |   PostgreSQL
    |
    v
Pydantic response schema
    |
    v
HTTP response
```

For documents:

```text
HTTP request
    |
    v
Document route
    |
    v
DocumentService
    |
    +--> authorization
    |
    +--> MinIO
    |
    +--> DocumentRepository
              |
              v
          PostgreSQL
```

---


## 35. Recommended Evolution

As PropNest grows, the backend should evolve toward clear domain modules.

A mature structure can converge toward:

```text
app/
├── api/
│   └── v1/
│       └── routes/
├── core/
│   ├── config.py
│   ├── security.py
│   └── exceptions.py
├── db/
│   ├── session.py
│   └── base.py
├── models/
├── schemas/
├── repositories/
├── services/
├── storage/
└── main.py
```

Feature/domain organization may eventually be preferable if the number of modules increases substantially:

```text
app/
├── domains/
│   ├── users/
│   ├── properties/
│   ├── tenants/
│   ├── contracts/
│   ├── documents/
│   └── payments/
```

The team should not introduce this reorganization merely for aesthetics. It becomes valuable when cross-module navigation and ownership become difficult.

---


## 34. Architectural Invariants

The following should be treated as backend invariants:

1. Routes do not contain business workflows.
2. Services own business rules.
3. Repositories own persistence mechanics.
4. FastAPI is not used as a domain service inside repositories.
5. Authorization is enforced on the backend.
6. Transactions have one clear owner.
7. Database transactions are not assumed to include MinIO.
8. Storage keys are unique independently of original filenames.
9. Tests cannot silently use a real database.
10. API contracts are explicitly modeled.
11. Operational scripts follow the same async database architecture.
12. Passwords and tokens are never logged.
13. Database schema changes are migrated through Alembic.

---

