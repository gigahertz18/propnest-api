#!/usr/bin/env python3
"""
scripts/seed_admin.py

Creates the initial admin user for PropNest.
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

import os
import sys
import uuid

# ── make sure the app package is importable when run from /app ────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.base import TimestampMixin  # noqa: F401 — ensure TimestampMixin is loaded
from app.models.user import User, UserRole
from app.core.security import hash_password
from app.models import Property, Contract, Tenant, Document  # noqa: F401 — register all models


# ── Credentials from environment ──────────────────────────────────────────────

USERNAME  = os.environ.get("SEED_USERNAME",  "admin")
EMAIL     = os.environ.get("SEED_EMAIL",     "admin@propnest.com")
FULL_NAME = os.environ.get("SEED_FULL_NAME", "PropNest Admin")
PASSWORD  = os.environ.get("SEED_PASSWORD",  "")


def _validate() -> None:
    if not PASSWORD:
        print(
            "\n[seed] ERROR: SEED_PASSWORD is required.\n"
            "       Set it via environment variable or use:\n"
            "       make seed password=yourpassword\n"
        )
        sys.exit(1)

    if len(PASSWORD) < 8:
        print("\n[seed] ERROR: SEED_PASSWORD must be at least 8 characters.\n")
        sys.exit(1)


def seed() -> None:
    _validate()

    db = SessionLocal()

    try:
        # ── Check for existing user ────────────────────────────────────────────
        existing_username = (
            db.query(User).filter(User.username == USERNAME).first()
        )
        existing_email = (
            db.query(User).filter(User.email == EMAIL).first()
        )

        if existing_username:
            print(
                f"\n[seed] Skipped — username '{USERNAME}' already exists.\n"
                f"       User ID : {existing_username.id}\n"
                f"       Role    : {existing_username.role.value}\n"
                f"       Active  : {existing_username.is_active}\n"
            )
            return

        if existing_email:
            print(
                f"\n[seed] Skipped — email '{EMAIL}' already exists.\n"
                f"       Username: {existing_email.username}\n"
                f"       User ID : {existing_email.id}\n"
            )
            return

        # ── Create admin user ──────────────────────────────────────────────────
        admin = User(
            id=uuid.uuid4(),
            username=USERNAME,
            email=EMAIL,
            full_name=FULL_NAME,
            password_hash=hash_password(PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )

        db.add(admin)
        db.commit()
        db.refresh(admin)

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
        db.rollback()
        print(f"\n[seed] ERROR: {e}\n")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
