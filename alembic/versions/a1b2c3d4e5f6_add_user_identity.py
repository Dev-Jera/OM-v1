"""add user identity fields (name, email)

Revision ID: a1b2c3d4e5f6
Revises: c3d4e5f6a7b8
Create Date: 2026-08-17 12:00:00.000000

Stores the client's name (masked in analytics as :clients_name) and email
(collected for follow-up) on the users table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(length=200), nullable=True))
    op.add_column(
        "users",
        sa.Column("identity_captured_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_column("users", "identity_captured_at")
    op.drop_column("users", "email")
    op.drop_column("users", "name")