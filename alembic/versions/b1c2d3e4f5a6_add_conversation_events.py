"""add conversation events table

Revision ID: b1c2d3e4f5a6
Revises: c3d4e5f6a7b8
Create Date: 2026-03-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("conversation_events"):
        op.create_table(
            "conversation_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("conversation_id", sa.String(length=36), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(bind)

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("conversation_events")}
    if op.f("ix_conversation_events_conversation_id") not in existing_indexes:
        op.create_index(op.f("ix_conversation_events_conversation_id"), "conversation_events", ["conversation_id"], unique=False)
    if op.f("ix_conversation_events_event_type") not in existing_indexes:
        op.create_index(op.f("ix_conversation_events_event_type"), "conversation_events", ["event_type"], unique=False)
    if op.f("ix_conversation_events_created_at") not in existing_indexes:
        op.create_index(op.f("ix_conversation_events_created_at"), "conversation_events", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("conversation_events"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("conversation_events")}
        if op.f("ix_conversation_events_created_at") in existing_indexes:
            op.drop_index(op.f("ix_conversation_events_created_at"), table_name="conversation_events")
        if op.f("ix_conversation_events_event_type") in existing_indexes:
            op.drop_index(op.f("ix_conversation_events_event_type"), table_name="conversation_events")
        if op.f("ix_conversation_events_conversation_id") in existing_indexes:
            op.drop_index(op.f("ix_conversation_events_conversation_id"), table_name="conversation_events")
        op.drop_table("conversation_events")
