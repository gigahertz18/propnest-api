# PropNest Backend — Overview

## 1. Purpose

This document describes the current software design of the PropNest backend.

The backend is the authoritative application/service layer for the PropNest platform. It owns domain rules, persistence, authorization, transactions, file metadata, object-storage operations, and the HTTP API consumed by the web frontend.

This document captures the architecture established through the project's backend implementation and refactoring work.

Because this document is being created from the project context accumulated during development rather than from a newly supplied complete backend repository snapshot, details that may have changed after the last reviewed backend state should be treated as implementation facts to re-verify when this document is adopted.

---


## 2. Product Context

PropNest is a property-management SaaS application.

The backend models and exposes core property-management capabilities including:

- users and authentication
- properties
- tenants
- contracts / leases
- documents
- collections (document grouping)
- payments
- role-based access

The backend is intentionally layered so that domain rules are not embedded directly in HTTP route handlers.

---


## 3. Architectural Goals

The backend architecture follows these goals:

1. **HTTP concerns belong in routes.**
2. **Business rules belong in services.**
3. **Persistence belongs in repositories.**
4. **Database structure belongs in models/migrations.**
5. **API contracts belong in schemas.**
6. **Authorization is enforced server-side.**
7. **Database access is asynchronous.**
8. **External object storage is treated as a separate side-effecting system.**
9. **Transactions must be designed explicitly where multiple side effects are involved.**
10. **Tests should isolate layers and provide integration coverage at HTTP/database boundaries.**

---


## 39. System-Level Design Summary

PropNest is intentionally split into two independently deployable application layers.

### Web

```text
Next.js
  |
  | secure server-side API proxy
  v
FastAPI
```

### API

```text
FastAPI
  |
  +--> Services
        |
        +--> Repositories
              |
              v
          PostgreSQL

        +
        |
        v
      MinIO
```

The primary architectural boundary is therefore:

> **The frontend owns presentation and user interaction; the backend owns domain truth, authorization, persistence, and integration with infrastructure services.**

That boundary should remain stable as the product grows.


## 37. Current High-Risk Areas

The following deserve continued engineering attention:

### A. Database/storage consistency

Document operations span PostgreSQL and MinIO and therefore require explicit failure handling.

### B. Property ownership establishment

`manager_id` must be reliably assignable through real application workflows.

### C. Transaction ownership

The application should not rely on both services and `get_db()` committing independently.

### D. Pagination consistency

Collection endpoints should use a common pagination contract.

### E. Authorization coverage

Resource-scope authorization must be tested for each supported role.

### F. Async architecture consistency

Application code, migrations, scripts, and tests must agree on sync vs async database access patterns.

---



## Roadmap status

The backend roadmap is explicitly phase-based, with Phase 2 establishing the core long-term rental billing loop and an internal alpha serving as the validation gate before Phase 3+ expansion.

See [Roadmap Alignment](roadmap-alignment.md) and [Beta Roadmap](../product/beta-roadmap.md).
