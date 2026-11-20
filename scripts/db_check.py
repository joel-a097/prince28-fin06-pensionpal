"""Verify the Neon database connection.

Run:  uv run python scripts/db_check.py
Expect: Connected to database '...'
        PostgreSQL 17.x ...
"""

import asyncio

from sqlalchemy import text

from pensionpal.config import get_settings
from pensionpal.db.session import make_engine


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings)
    async with engine.connect() as conn:
        row = await conn.execute(text("SELECT current_database(), version()"))
        db_name, version = row.one()
        print(f"Connected to database '{db_name}'")
        print(version)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
