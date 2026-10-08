"""One-off cleanup: drop the retired topic / keyword tables and columns.

Run from the backend directory with the project venv:
    ./.venv/bin/python -m scripts.cleanup_legacy_topics

Destructive by design (Master approved dropping the legacy preset data).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.db import dispose_engine, get_engine

TABLES = ["topics", "keywords", "topic_sources", "item_topics"]


async def main() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        for table in TABLES:
            exists = await conn.scalar(
                text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}
            )
            if exists is None:
                print(f"skip (absent): {table}")
                continue
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
            print(f"dropped table: {table}")
        await conn.execute(text("ALTER TABLE digests DROP COLUMN IF EXISTS topic_id"))
        print("dropped column (if existed): digests.topic_id")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
