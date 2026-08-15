# PropNest Backend — API Contracts and Pagination

## 15. Error Architecture

The service layer uses domain-oriented exceptions rather than making every service function return HTTP responses.

Examples established during development include concepts such as:

```text
RelatedResourceNotFoundError
```

The desired pattern is:

```text
Service
  |
  | raise domain exception
  v
Route / global exception handler
  |
  | map to HTTP status
  v
API response
```

This keeps domain code independent from FastAPI response classes.

---


## 16. Validation Boundaries

Validation should occur at multiple levels, with different responsibilities.

### Pydantic schema validation

Handles:

- type validation
- required/optional fields
- basic field constraints
- request shape

### Service validation

Handles:

- domain rules
- relationship existence where relevant
- authorization
- state transitions
- cross-entity constraints

### Database constraints

Handles:

- uniqueness
- foreign keys
- not-null constraints
- referential integrity

The layers should complement each other rather than duplicate all rules everywhere.

---


## 17. Pagination

List endpoints should return a consistent pagination envelope.

The project has discussed introducing:

```python
PaginatedResponse[T]
```

with fields conceptually similar to:

```text
items
total
skip / offset
limit
```

This is preferable to returning an unstructured list when the backend exposes potentially large collections.

A list operation therefore typically requires:

```text
data query
+
count query
```

The service/repository layer should keep pagination mechanics reusable.

---


## 24. API Versioning

The frontend currently calls the backend under:

```text
/api/v1
```

Therefore the backend API is versioned at the HTTP boundary.

This provides room to introduce a future `/api/v2` without immediately breaking the existing frontend.

Versioning should be applied consistently rather than only to selected resources.

---


## 25. Frontend/Backend Contract

The system boundary is:

```text
PropNest Web
    |
    | HTTP / JSON / multipart
    v
PropNest API
```

The frontend should depend only on documented API behavior.

The backend should not depend on frontend implementation details.

Important contract categories include:

- authentication responses
- user roles
- property resource fields
- document upload response shape
- HTTP status codes
- error `detail`
- pagination shape

A future improvement should be generated TypeScript API types from FastAPI's OpenAPI schema to reduce duplicated interface definitions.

---

