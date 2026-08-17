"""add_composite_index_to_audit_logs

Revision ID: 967935f1428a
Revises: 9a07b1630d76
Create Date: 2026-08-17 05:33:29.072535

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "967935f1428a"
down_revision: Union[str, None] = "9a07b1630d76"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CONCURRENTLY avoids locking audit_logs against writes while the index
    # builds — audit rows are appended by every mutating service on the
    # request path, so a blocking build here would stall unrelated writes
    # across the app. Requires running outside the migration's transaction.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_audit_logs_entity_type_entity_id",
            "audit_logs",
            ["entity_type", "entity_id"],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_audit_logs_entity_type_entity_id",
            table_name="audit_logs",
            postgresql_concurrently=True,
        )
