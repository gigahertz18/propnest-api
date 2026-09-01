#!/usr/bin/env python3
"""
scripts/seed_admin.py

One-off operational script for bootstrapping the initial admin user in a
new PropNest environment.

This is NOT part of the application runtime. It talks to the database
directly — it does not go through the API, service, or repository
layers — and is meant to be run manually (or via `make seed`) once per
environment, typically right after running migrations. It is
intentionally simple and hand-rolled rather than reusing
`UserService`/`UserRepository`.
Safe to run multiple times — skips creation if the username or email
already exists rather than erroring.

Usage (inside the backend container):
    python scripts/seed_admin.py

Credentials are passed via environment variables:
    SEED_USERNAME   default: admin
    SEED_EMAIL      default: admin@propnest.com
    SEED_PASSWORD   required — no default, script exits if missing
    SEED_FULL_NAME  default: PropNest Admin

Run via make:
    make seed
    make seed password=mypassword123
"""

import asyncio
import os
import sys
import uuid

# ── make sure the app package is importable when run from /app ────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from sqlalchemy import select  # noqa: E402

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.core.models.base import TimestampMixin  # noqa: F401 — ensure TimestampMixin is loaded
from app.models.user import User, UserRole  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Property, Contract, Tenant, Document  # noqa: F401 — register all models


def _get_credentials() -> tuple[str, str, str, str]:
    """
    Read seed credentials from the environment.

    Deliberately read at call time rather than at import time, so this
    module can be imported (e.g by the smoke test in `tests/integration/test_seed_admin.py`)
    without the values being frozen before the caller has a chance to set them via monkeypatch.

    Returns (username, email, full_name, password)
    """

    username = os.environ.get("SEED_USERNAME", "admin")
    email = os.environ.get("SEED_EMAIL", "admin@propnest.com")
    full_name = os.environ.get("SEED_FULL_NAME", "PropNest Admin")
    password = os.environ.get("SEED_PASSWORD", "")
    return username, email, full_name, password


def _validate(password: str) -> None:
    if not password:
        print(
            "\n[seed] ERROR: SEED_PASSWORD is required.\n"
            "       Set it via environment variable or use:\n"
            "       make seed password=yourpassword\n"
        )
        sys.exit(1)

    if len(password) < 8:
        print("\n[seed] ERROR: SEED_PASSWORD must be at least 8 characters.\n")
        sys.exit(1)


async def seed() -> None:
    username, email, full_name, password = _get_credentials()
    _validate(password)

    async with AsyncSessionLocal() as db:
        try:
            # Check for existing user
            existing_username = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
            existing_email = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if existing_username:
                print(
                    f"\n[seed] Skipped — username '{username}' already exists.\n"
                    f"       User ID : {existing_username.id}\n"
                    f"       Role    : {existing_username.role.value}\n"
                    f"       Active  : {existing_username.is_active}\n"
                )
                return

            if existing_email:
                print(
                    f"\n[seed] Skipped — email '{email}' already exists.\n"
                    f"       Username: {existing_email.username}\n"
                    f"       User ID : {existing_email.id}\n"
                )
                return

            # ── Create admin user ──────────────────────────────────────────────────
            admin = User(
                id=uuid.uuid4(),
                username=username,
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                role=UserRole.ADMIN,
                is_active=True,
            )

            db.add(admin)
            await db.commit()
            await db.refresh(admin)

            print(
                f"\n[seed] Admin user created successfully.\n"
                f"       Username : {admin.username}\n"
                f"       Email    : {admin.email}\n"
                f"       Full name: {admin.full_name}\n"
                f"       User ID  : {admin.id}\n"
                f"       Role     : {admin.role.value}\n"
                f"\n       Log in at http://localhost:3000/login\n"
            )
        except Exception as e:
            await db.rollback()
            print(f"\n[seed] ERROR: {e}\n")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(seed())
