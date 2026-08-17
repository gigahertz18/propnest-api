"""add_receipts_table

Revision ID: fbd272996f88
Revises: a3f7c92e1b6d
Create Date: 2026-08-17 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "fbd272996f88"
down_revision: Union[str, None] = "a3f7c92e1b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("receipt_number", sa.Integer(), sa.Identity(start=1, increment=1), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_receipts"),
    )
    op.create_index(op.f("ix_receipts_receipt_number"), "receipts", ["receipt_number"], unique=True)
    op.create_index(op.f("ix_receipts_payment_id"), "receipts", ["payment_id"], unique=False)
    op.create_unique_constraint("uq_receipts_document_id", "receipts", ["document_id"])
    op.create_foreign_key("receipts_payment_id_fkey", "receipts", "payments", ["payment_id"], ["id"])
    op.create_foreign_key("receipts_document_id_fkey", "receipts", "documents", ["document_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("receipts_document_id_fkey", "receipts", type_="foreignkey")
    op.drop_constraint("receipts_payment_id_fkey", "receipts", type_="foreignkey")
    op.drop_constraint("uq_receipts_document_id", "receipts", type_="unique")
    op.drop_index(op.f("ix_receipts_payment_id"), table_name="receipts")
    op.drop_index(op.f("ix_receipts_receipt_number"), table_name="receipts")
    op.drop_table("receipts")
