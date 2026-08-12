"""Add server_default now() to created_at across all tables.

Revision ID: a1f3c9e07d42
Revises: 20dc3a8be02c
Create Date: 2026-08-12 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1f3c9e07d42"
down_revision: Union[str, None] = "20dc3a8be02c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["users", "properties", "tenants", "contracts", "documents", "payments"]


def upgrade() -> None:
    for table in TABLES:
        op.alter_column(
            table,
            "created_at",
            server_default=sa.text("now()"),
        )


def downgrade() -> None:
    for table in TABLES:
        op.alter_column(
            table,
            "created_at",
            server_default=None,
        )
