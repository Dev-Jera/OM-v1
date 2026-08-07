"""compatibility bridge revision

Revision ID: c3d4e5f6a7b8
Revises: 8f4c9e3b7a2a
Create Date: 2026-03-25 00:00:00.000000

This is an intentionally empty migration that restores a missing historical
revision id used by some deployed environments.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "8f4c9e3b7a2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op bridge migration for compatibility with existing DB revision stamps.
    pass


def downgrade() -> None:
    # No-op bridge migration for compatibility with existing DB revision stamps.
    pass
