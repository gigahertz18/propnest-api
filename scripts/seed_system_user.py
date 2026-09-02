#!/usr/bin/env python3
"""
scripts/seed_system_user.py

One-off operational script for bootstrapping the dedicated billing-job
system identity in a new PropNest environment (see
app/jobs/billing_jobs.py, docs/deployment-operations.md).

Mirrors scripts/seed_admin.py's structure and safety conventions: talks
to the database directly (no API/service/repository layers), is meant to
be run manually (or via `make seed-system`) once per environment right
after migrations, and is safe to run multiple times — skips creation if
a user with settings.SYSTEM_SCHEDULER_USER_ID already exists rather than
erroring.

This identity is role=ADMIN (so LeaseBillingService's existing
_authorize_user_to_property bypass for admins applies with no service-
layer changes) but is intentionally impossible to log in as:

  - Its password_hash is derived from a random 64-byte token generated
    here and never printed, logged, or persisted anywhere else — there is
    no legitimate credential to "know."
  - AuthService.login additionally refuses this identity outright by
    username/email, as defense-in-depth on top of the unguessable
    password (see app/identity/services/auth_service.py).

Usage (inside the backend container):
    python scripts/seed_system_user.py
"""

import asyncio
import os
import sys

# ── make sure the app package is importable when run from /app ────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from app.db.seed import seed_system_user  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402


async def seed() -> None:

    async with AsyncSessionLocal() as db:
        try:
            system_user, created = await seed_system_user(db)
            if not created:
                print(
                    f"\n[seed] Skipped — system scheduler user already exists.\n"
                    f"       User ID : {system_user.id}\n"
                    f"       Username: {system_user.username}\n"
                    f"       Role    : {system_user.role.value}\n"
                    f"       Active  : {system_user.is_active}\n"
                )
                return

            print(
                f"\n[seed] System scheduler user created successfully.\n"
                f"       Username : {system_user.username}\n"
                f"       Email    : {system_user.email}\n"
                f"       User ID  : {system_user.id}\n"
                f"       Role     : {system_user.role.value}\n"
                f"\n       This identity cannot log in — AuthService.login refuses it by design.\n"
            )
        except Exception as e:
            await db.rollback()
            print(f"\n[seed] ERROR: {e}\n")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(seed())
