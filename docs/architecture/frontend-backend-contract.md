# PropNest — Frontend–Backend Contract

## Runtime boundary

```text
Browser
  |
  | /api/...
  v
Next.js Route Handler
  |
  | Authorization: Bearer <token>
  v
FastAPI /api/v1/...
```

## Responsibility boundary

The frontend depends on documented API behavior and must not depend on backend repository or database implementation details.

The backend must not depend on frontend components or browser state.

## Shared contract areas

- authentication responses
- user roles
- property resource fields
- create/update payloads
- document/image upload responses
- HTTP status codes
- error `detail` responses
- pagination envelopes

## Current constraint

The frontend duplicates some backend types manually. A future improvement is to generate TypeScript types/client code from FastAPI OpenAPI.

## Security rule

Frontend role checks are for UX. Backend authorization is the security boundary.
