#!/usr/bin/env python3
"""
scripts/export_openapi.py

Dumps the live OpenAPI schema (generated from route/schema definitions, not
a running server) to a JSON file for the frontend team to reference. Does
not require db/redis/minio to be running — importing app.main does not
trigger its lifespan context manager, which only executes on ASGI startup.

Usage (inside the backend container):
    python scripts/export_openapi.py [output_path]

Output defaults to openapi.json at the repo root (gitignored — this is
generate-on-demand, never committed).

Run via make:
    make export-openapi
"""

import json
import os
import sys

# ── make sure the app package is importable when run from /app ────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402


def main() -> None:
    output_path = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
    with open(output_path, "w") as f:
        json.dump(app.openapi(), f, indent=2)
    print(f"OpenAPI schema written to {output_path}")


if __name__ == "__main__":
    main()
