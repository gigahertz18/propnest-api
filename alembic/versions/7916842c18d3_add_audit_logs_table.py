"""add_audit_logs_table

Revision ID: 7916842c18d3
Revises: 953edb35f418
Create Date: 2026-08-16 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7916842c18d3"
down_revision: Union[str, None] = "953edb35f418"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

audit_action_enum = postgresql.ENUM("CREATE", "UPDATE", "DELETE", name="auditaction")
audit_action_column_type = postgresql.ENUM("CREATE", "UPDATE", "DELETE", name="auditaction", create_type=False)


def upgrade() -> None:
    audit_action_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", audit_action_column_type, nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"])
    op.create_index(op.f("ix_audit_logs_entity_type"), "audit_logs", ["entity_type"])
    op.create_index(op.f("ix_audit_logs_entity_id"), "audit_logs", ["entity_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_entity_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_entity_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_table("audit_logs")

    audit_action_enum.drop(op.get_bind(), checkfirst=True)
