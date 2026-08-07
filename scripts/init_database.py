#!/usr/bin/env python3
"""
Create app tables in Postgres, including users, conversations, messages, quotes,
PersonalAccidentApplication, TravelInsuranceApplication, SerenicareApplication.

Uses DATABASE_URL environment variable. Does NOT drop existing tables.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Make sure src is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

# Import all models so SQLAlchemy knows about them
from src.database.models import (
    Base,
    User,
    Conversation,
    Message,
    Quote,
    PersonalAccidentApplication,
    TravelInsuranceApplication,
    SerenicareApplication,
)
from src.database.postgres_real import _normalize_connection_string

def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    url = _normalize_connection_string(url)

    try:
        engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)

        # Test connection using text()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Database connection OK")

        # Create all tables (only missing ones will be added)
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print("✅ App tables now exist:", sorted(tables))
        return 0

    except OperationalError as e:
        print(f"❌ Failed to connect to database: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())



"""
Create app tables (users, conversations, messages, quotes) in Postgres.
Uses DATABASE_URL. Run when USE_POSTGRES_CONVERSATIONS is enabled.
"""
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.database.models import Base
from sqlalchemy import create_engine


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    print("App tables created (users, conversations, messages, quotes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
