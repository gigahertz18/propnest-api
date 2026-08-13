"""enforce_contract_and_payment_status_enums

Revision ID: e946b8cb5e39
Revises: a1f3c9e07d42
Create Date: 2026-08-13 03:31:50.749715

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e946b8cb5e39"
down_revision: Union[str, None] = "a1f3c9e07d42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

contract_status_enum = postgresql.ENUM("ACTIVE", "EXPIRED", "TERMINATED", name="contract_status_enum")
payment_status_enum = postgresql.ENUM("PAID", "PENDING", "REFUNDED", name="payment_status_enum")


def upgrade() -> None:
    contract_status_enum.create(op.get_bind(), checkfirst=True)
    payment_status_enum.create(op.get_bind(), checkfirst=True)

    # The partial unique index's predicate blocks an in-place type change
    # ("functions in index predicate must be marked IMMUTABLE") - drop and recreate it.
    op.drop_index("uq_active_contract_property", table_name="contracts")

    op.execute("ALTER TABLE contracts ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE contracts ALTER COLUMN status TYPE contract_status_enum "
        "USING status::text::contract_status_enum"
    )
    op.execute("ALTER TABLE contracts ALTER COLUMN status SET DEFAULT 'ACTIVE'::contract_status_enum")

    op.create_index(
        "uq_active_contract_property",
        "contracts",
        ["property_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.execute(
        "ALTER TABLE payments ALTER COLUMN status TYPE payment_status_enum " "USING status::text::payment_status_enum"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE payments ALTER COLUMN status TYPE VARCHAR(10) USING status::text")

    op.drop_index("uq_active_contract_property", table_name="contracts")

    op.execute("ALTER TABLE contracts ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE contracts ALTER COLUMN status TYPE VARCHAR(10) USING status::text")
    op.execute("ALTER TABLE contracts ALTER COLUMN status SET DEFAULT 'ACTIVE'")

    op.create_index(
        "uq_active_contract_property",
        "contracts",
        ["property_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    payment_status_enum.drop(op.get_bind(), checkfirst=True)
    contract_status_enum.drop(op.get_bind(), checkfirst=True)
