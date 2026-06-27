ENV ?= dev

COMPOSE_FILE = docker-compose.yml
COMPOSE      = ENV=$(ENV) docker compose -f $(COMPOSE_FILE)

# Test commands always inject ENV=unittest into the exec'd process
# so UnittestConfig is used regardless of what ENV the container was started with
TEST_EXEC = $(COMPOSE) run --rm -e ENV=unittest

# ─── Main Commands ────────────────────────────────────────
up:
	$(COMPOSE) up --build

up-detached:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) down && $(COMPOSE) up --build

restart-detached:
	$(COMPOSE) down && $(COMPOSE) up -d --build

logs:
	$(COMPOSE) logs -f

# ─── Individual Service Logs ──────────────────────────────
logs-backend:
	$(COMPOSE) logs -f backend

logs-db:
	$(COMPOSE) logs -f db

logs-minio:
	$(COMPOSE) logs -f minio

# ─── Shells ───────────────────────────────────────────────
db-shell:
	$(COMPOSE) exec db psql -U propnest -d propnest_db

be-shell:
	$(COMPOSE) exec -it backend sh


# ─── Seed ─────────────────────────────────────────────────
# Creates the initial admin user. Password is required.
# Usage:
#   make seed password=yourpassword
#   make seed password=yourpassword username=superadmin email=you@example.com
seed:
	@if [ -z "$(password)" ]; then \
		echo "\n[seed] ERROR: password is required.\n       Usage: make seed password=yourpassword\n"; \
		exit 1; \
	fi
	$(COMPOSE) exec \
		-e SEED_PASSWORD=$(password) \
		-e SEED_USERNAME=$(or $(username),admin) \
		-e SEED_EMAIL=$(or $(email),admin@propnest.com) \
		-e SEED_FULL_NAME="$(or $(fullname),PropNest Admin)" \
		backend \
		python scripts/seed_admin.py

# ─── Migrations ───────────────────────────────────────────
migrate-new:
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(msg)"

migrate-up:
	$(COMPOSE) exec backend alembic upgrade head

migrate-down:
	$(COMPOSE) exec backend alembic downgrade -1

migrate-history:
	$(COMPOSE) exec backend alembic history

# ─── Backend Tests ────────────────────────────────────────
# All test commands use TEST_EXEC which injects ENV=unittest
test-be:
	$(TEST_EXEC) backend pytest $(debug)

test-be-unit:
	$(TEST_EXEC) backend pytest tests/unittests $(debug)

test-be-integration:
	$(TEST_EXEC) backend pytest tests/integration $(debug)

# test-be-e2e:
# 	$(TEST_EXEC) backend pytest tests/e2e $(debug)

test-be-file:
	$(TEST_EXEC) backend pytest $(file) $(debug)

test-be-cov:
	$(TEST_EXEC) backend pytest --cov=app --cov-report=term-missing $(debug)

# ─── Backend Lint & Format ───────────────────────────────
lint-be:
	$(TEST_EXEC) backend ruff check app

lint-be-fix:
	$(TEST_EXEC) backend ruff check app --fix

format-be:
	$(TEST_EXEC) backend black --check --line-length 120 app

# ─── Helpers ──────────────────────────────────────────────
ps:
	$(COMPOSE) ps

clean:
	$(COMPOSE) down -v --remove-orphans

.PHONY: up up-detached down restart restart-detached logs \
        logs-backend logs-db logs-minio \
        db-shell be-shell seed \
        migrate-new migrate-up migrate-down migrate-history \
        test-be test-be-unit test-be-integration \
        test-be-file test-be-cov \
		lint-be lint-be-fix format-be \
		ps clean
