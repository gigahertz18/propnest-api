# PropNest API 🏠

A backend service for managing long-term and short-term property rentals — tenants, leases, contracts, payments, and supporting documents.

This repo is the standalone backend, extracted from the original PropNest monorepo to stand on its own as a focused showcase of backend architecture, testing, and CI practices. The companion frontend lives in [`propnest-web`](#) (Next.js).

---

## Why this project

I built this to go deeper on patterns I use professionally but wanted to demonstrate end-to-end on my own: a layered backend architecture (routes → services → repositories → models), authentication done properly, database migrations instead of `create_all()`, and a CI pipeline that actually gates on lint, format, tests, and dependency vulnerabilities — not just "it runs."

Parts of this project were built with AI assistance. The architecture, schema design, and testing strategy are my own; I used AI as a tool during implementation the way I would a pair programmer, and I can walk through and defend any part of this codebase.

---

## Tech Stack

| Layer | Tech |
|---|---|
| Framework | FastAPI (Python) |
| Database | PostgreSQL 16 |
| ORM / Migrations | SQLAlchemy + Alembic |
| File Storage | MinIO (S3-compatible) |
| Auth | JWT (access tokens, issuer/audience scoped) |
| Containerization | Docker + Docker Compose |
| Linting / Formatting | ruff, black |
| Testing | pytest (unit + integration), pytest-cov |
| Security | gitleaks (secret scanning in CI), safety (dependency vulnerability checks) |
| CI | GitHub Actions |

---

## Architecture

The backend follows a layered structure to keep business logic out of the HTTP layer and out of the ORM layer:

```
app/
├── api/v1/routes/      # HTTP layer — request/response handling only
├── services/           # Business logic, orchestration, domain exceptions
├── repositories/       # Data access — generic CRUD base + per-entity repos
├── models/             # SQLAlchemy models (User, Property, Tenant, Contract, Payment, Document)
├── schemas/            # Pydantic request/response schemas
├── core/                # Config (env-based: dev/test/staging/prod), security, logging, dependencies
└── db/                  # Session management
```

**Why this split:** routes stay thin and testable in isolation; services hold the actual business rules and raise domain-specific exceptions (not HTTP exceptions) so they're reusable outside the web layer; repositories isolate persistence so the ORM can be swapped or mocked without touching business logic.

**Config** is environment-aware via a small class hierarchy (`BaseConfig` → `DevelopmentConfig` / `UnittestConfig` / staging / prod), so tests run against a dedicated test database and never touch dev data.

---

## Getting Started

Requires Docker and Docker Compose.

```bash
git clone https://github.com/gigahertz18/propnest-api.git
cd propnest-api
make up
```

This starts the API, PostgreSQL, and MinIO. The API will be available at `http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`.

Run database migrations:
```bash
make migrate-up
```

Seed an admin user:
```bash
make seed password=yourpassword
```

---

## Testing & Quality

```bash
make test-be              # full suite
make test-be-unit         # unit tests only
make test-be-integration  # integration tests (incl. MinIO)
make test-be-cov          # with coverage report
make lint-be               # ruff
make format-be             # black --check
```

The suite includes concurrency-focused repository tests (e.g. concurrent writes to contracts) alongside standard unit and integration coverage of services, repositories, and routes.

Every push and PR runs through CI: secret scanning (gitleaks) → lint → format check → tests → dependency vulnerability scan (safety). See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## What I'd do differently at scale

- Move from polling-based DB retry on startup to a proper readiness probe / health check pattern for orchestration (Kubernetes-friendly).
- Add structured request tracing (correlation IDs) across the logging setup for multi-instance debugging.
- Introduce a metrics endpoint (Prometheus-compatible) — currently logging-only, no time-series observability.
- Move from single-VM Docker Compose to a Kubernetes deployment with separate scaling for the API vs. background/migration jobs.

---

## License

MIT (or update to your preference)
