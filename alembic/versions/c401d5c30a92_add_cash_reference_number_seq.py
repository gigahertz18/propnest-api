"""add_cash_reference_number_seq

Revision ID: c401d5c30a92
Revises: 967935f1428a
Create Date: 2026-09-07 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c401d5c30a92"
down_revision: Union[str, None] = "967935f1428a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Standalone sequence, not attached to any column — only cash payments
    # need an allocated value, so an Identity-backed column (which every row
    # would advance on insert) would be the wrong shape here.
    op.execute("CREATE SEQUENCE cash_reference_number_seq")


def downgrade() -> None:
    op.execute("DROP SEQUENCE cash_reference_number_seq")
