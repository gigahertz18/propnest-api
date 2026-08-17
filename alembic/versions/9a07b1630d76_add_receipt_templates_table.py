"""add_receipt_templates_table

Revision ID: 9a07b1630d76
Revises: fbd272996f88
Create Date: 2026-08-17 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9a07b1630d76"
down_revision: Union[str, None] = "fbd272996f88"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "receipt_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("file_url", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_receipt_templates"),
    )
    op.create_index(op.f("ix_receipt_templates_property_id"), "receipt_templates", ["property_id"], unique=False)
    op.create_foreign_key(
        "receipt_templates_property_id_fkey", "receipt_templates", "properties", ["property_id"], ["id"]
    )

    # One active template per scope (a specific property_id, or globally
    # when NULL) — coalesced to a sentinel UUID for the global case, since
    # a plain unique index on property_id would let multiple NULL rows
    # through (Postgres treats NULLs as distinct).
    op.create_index(
        "uq_active_receipt_template_scope",
        "receipt_templates",
        [sa.text("COALESCE(property_id, '00000000-0000-0000-0000-000000000000'::uuid)")],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_receipt_template_scope", table_name="receipt_templates")
    op.drop_constraint("receipt_templates_property_id_fkey", "receipt_templates", type_="foreignkey")
    op.drop_index(op.f("ix_receipt_templates_property_id"), table_name="receipt_templates")
    op.drop_table("receipt_templates")
