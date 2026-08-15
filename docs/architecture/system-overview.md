# PropNest — System Overview

PropNest is split into a Next.js web application and a FastAPI backend.

```text
Browser
   |
   v
Next.js
   |
   | server-side authenticated API calls
   v
FastAPI
   |
   +--> PostgreSQL
   |
   +--> MinIO
```

## Responsibility boundary

The frontend owns presentation, browser interaction, navigation, client session state, and same-origin API access.

The backend owns domain rules, authorization, persistence, transactions, file metadata, object-storage integration, and API contracts.

See:

- [Frontend Architecture](../frontend/architecture.md)
- [Backend Architecture](../backend/architecture.md)
- [Frontend–Backend Contract](frontend-backend-contract.md)
