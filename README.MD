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
| Auth | JWT (access tokens, issuer/audience scoped) + Redis-backed per-IP rate limiting and per-identifier login lockout |
| Cache / Ephemeral State | Redis |
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
├── repositories/       # Data access — generic CRUD base + per-entity repos (plus two Redis-backed ones: LoginAttemptRepository for login lockout, IpRateLimitRepository for per-IP throttling)
├── models/             # SQLAlchemy models (User, Property, Tenant, Contract, Payment, Document)
├── schemas/            # Pydantic request/response schemas
├── core/                # Config (env-based: dev/test/staging/prod), security, logging, dependencies
└── db/                  # Session management
```

**Why this split:** routes stay thin and testable in isolation; services hold the actual business rules and raise domain-specific exceptions (not HTTP exceptions) so they're reusable outside the web layer; repositories isolate persistence so the ORM can be swapped or mocked without touching business logic.

**Transaction ownership:** service methods own database commits. The shared `get_db()` dependency only opens the session for the request and rolls back on exception; it does not commit.

**Login throttling:** `/auth/login` is protected by two independent layers above credential checking, both enforced inside `AuthService.login` — a per-IP request rate limit (`IpRateLimitRepository`, async-native fixed-window counter) and a per-identifier progressive lockout after repeated failures (`LoginAttemptRepository`). Lockout is keyed on the normalized identifier itself, not the user id, so a nonexistent username locks out identically to a real one — this preserves the existing timing-attack/enumeration protections in `verify_password` instead of reopening them through a 429-vs-401 difference. Both mechanisms are backed by Redis so they hold across multiple backend instances, and both fail closed: if Redis is unreachable, login is rejected (503) rather than silently proceeding unthrottled.

**Config** is environment-aware via a small class hierarchy (`BaseConfig` → `DevelopmentConfig` / `UnittestConfig` / staging / prod), so tests run against a dedicated test database and never touch dev data.

---

## Getting Started

Requires Docker and Docker Compose.

```bash
git clone https://github.com/gigahertz18/propnest-api.git
cd propnest-api
make up
```

This starts the API, PostgreSQL, and MinIO and Redis. The API will be available at `http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`.

Run database migrations:
```bash
make migrate-up
```

Seed an admin user:
```bash
make seed password=yourpassword
```

---

## Deploying

`docker-compose.yml` (the file `make up` uses) is dev-postured on purpose: it bind-mounts
the source tree, and publishes Postgres/MinIO/Redis directly to the host so they're easy
to inspect locally. **Don't reuse it against a reachable server** — none of its
credentials are meant to survive outside a laptop.

`docker-compose.prod.yml` is the deployable counterpart: it runs the built image only (no
bind mount), starts the app with `ENV=prod`, publishes only the API's port (8000), and
keeps Postgres/MinIO/Redis reachable only on the internal `propnest_network` — the same
way `backend` already reaches them. Redis is also started with `--requirepass`, since the
dev compose file's Redis has no authentication at all.

To deploy:

```bash
cp .env.prod.example .env.prod
# fill in .env.prod with real secrets - see the comments in the file

docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend alembic upgrade head
```

`ProductionConfig.validate()` (`app/core/config.py`) runs once at startup and refuses to
boot if any required secret is missing, empty, or still a known-insecure default — the
env vars below are what it checks:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required. Must be ≥32 characters and not a known-insecure default. |
| `DB_PASSWORD` | Required. Must not be a known-insecure default. |
| `MINIO_ROOT_PASSWORD` | Required. Must not be a known-insecure default. |
| `REDIS_PASSWORD` | Required. The Redis instance backing rate limiting/lockout must be configured with a matching `requirepass` (`docker-compose.prod.yml` does this). |
| `CORS_ORIGINS` | Optional, comma-separated frontend origins. Defaults to none if unset. |

This setup doesn't include a reverse proxy or TLS termination — that's out of scope for a
beta serving family users over a private/known-recipient link. If you do put this on a
reachable host, put a TLS terminator (e.g. Caddy or nginx) in front of port 8000 rather
than exposing it directly.

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
- Document deletion currently reorders the DB delete before the MinIO delete and logs (rather than reconciles) any storage object left behind by a failed cleanup. At scale, this should become soft-delete + an async purge job, once background task infra (Celery/APScheduler) exists for something else too — building it just for this one call site wasn't worth it yet.
- Service-exception-to-HTTP mapping (`app/main.py`) is currently one `@app.exception_handler` per exception family (`RelatedResourceNotFoundError` -> 404, `ResourceForbiddenError`/`UserForbiddenError` -> 403, `ServiceException` catch-all -> 500). An alternative considered: give each exception class in `app/services/exceptions.py` a `status_code` attribute and dispatch through a single generic handler that reads it off the instance — this would remove the need to touch `main.py` for new exception *families* at all (subclassing already gets free dispatch via MRO either way, so the practical gap is smaller than it looks). Not adopted: `exceptions.py`'s own module docstring states services must stay HTTP-agnostic ("no knowledge of HTTP... routes convert them to appropriate responses"), and putting `status_code` on the exception classes would break that boundary — worth revisiting only if that design principle changes.

---

## License

MIT (or update to your preference)
