"""add_collections_module

Revision ID: 953edb35f418
Revises: 1e9348aa4d61
Create Date: 2026-08-15 09:12:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "953edb35f418"
down_revision: Union[str, None] = "1e9348aa4d61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_collections_name"), "collections", ["name"])
    op.create_index(op.f("ix_collections_property_id"), "collections", ["property_id"])
    op.create_index(op.f("ix_collections_contract_id"), "collections", ["contract_id"])

    op.add_column("documents", sa.Column("collection_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "documents_collection_id_fkey",
        "documents",
        "collections",
        ["collection_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("documents_collection_id_fkey", "documents", type_="foreignkey")
    op.drop_column("documents", "collection_id")

    op.drop_index(op.f("ix_collections_contract_id"), table_name="collections")
    op.drop_index(op.f("ix_collections_property_id"), table_name="collections")
    op.drop_index(op.f("ix_collections_name"), table_name="collections")
    op.drop_table("collections")
