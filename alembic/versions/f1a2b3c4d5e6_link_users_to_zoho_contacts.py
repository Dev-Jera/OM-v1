"""link users to Zoho contacts (and merge divergent alembic heads)

Revision ID: f1a2b3c4d5e6
Revises: a1b2c3d4e5f6, b1c2d3e4f5a6
Create Date: 2026-08-17 14:00:00.000000

Adds users.zoho_contact_id so repeat-user detection can key on Zoho
contact identity (falling back to phone when unlinked). This revision also
merges the two existing alembic heads into one, so `alembic upgrade head`
works cleanly on fresh and existing databases.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = ("a1b2c3d4e5f6", "b1c2d3e4f5a6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {col["name"] for col in inspector.get_columns("users")}
    if "zoho_contact_id" not in columns:
        op.add_column(
            "users",
            sa.Column("zoho_contact_id", sa.String(length=64), nullable=True),
        )
        inspector = sa.inspect(bind)

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if op.f("ix_users_zoho_contact_id") not in existing_indexes:
        op.create_index(
            op.f("ix_users_zoho_contact_id"),
            "users",
            ["zoho_contact_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if op.f("ix_users_zoho_contact_id") in existing_indexes:
        op.drop_index(op.f("ix_users_zoho_contact_id"), table_name="users")
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "zoho_contact_id" in columns:
        op.drop_column("users", "zoho_contact_id")
