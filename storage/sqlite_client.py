import aiosqlite
from typing import Optional, Literal
import datetime

DB_FILE = "ozon.db"
TABLES = ["ozon_items", "wb_items"]

async def initialize_db():
    async with aiosqlite.connect(DB_FILE) as db:
        # Migration from old table name
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_urls'")
        if await cursor.fetchone():
            await db.execute("ALTER TABLE user_urls RENAME TO ozon_items")

        for table in TABLES:
            await db.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    user_id INTEGER,
                    url TEXT,
                    target_price REAL,
                    product_name TEXT,
                    added_at TIMESTAMP,
                    PRIMARY KEY (user_id, url)
                )
            """)
            # For backward compatibility, check and add columns if they don't exist
            cursor = await db.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in await cursor.fetchall()]
            if 'target_price' not in columns:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN target_price REAL")
            if 'product_name' not in columns:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN product_name TEXT")
            if 'added_at' not in columns:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN added_at TIMESTAMP")

        await db.commit()

async def add_item_for_user(user_id: int, url: str, product_name: str, table: str, target_price: Optional[float] = None):
    if table not in TABLES:
        raise ValueError(f"Invalid table name: {table}")
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            f"INSERT OR REPLACE INTO {table} (user_id, url, product_name, target_price, added_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, url, product_name, target_price, datetime.datetime.now())
        )
        await db.commit()

async def get_urls_for_user(user_id: int) -> list[tuple[int, str, str, Optional[float], str]]:
    all_rows = []
    async with aiosqlite.connect(DB_FILE) as db:
        for table in TABLES:
            cursor = await db.execute(f"SELECT rowid, url, product_name, target_price FROM {table} WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            # Add table name to each row
            all_rows.extend([row + (table,) for row in rows])
    return all_rows

async def get_all_tracked_urls() -> list[tuple[int, str, str, Optional[float]]]:
    all_rows = []
    async with aiosqlite.connect(DB_FILE) as db:
        for table in TABLES:
            cursor = await db.execute(f"SELECT user_id, url, product_name, target_price FROM {table}")
            rows = await cursor.fetchall()
            all_rows.extend(rows)
    return all_rows

async def remove_item_by_rowid(rowid: int, table_name: str):
    if table_name not in TABLES:
        raise ValueError(f"Invalid table name: {table_name}")
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(f"DELETE FROM {table_name} WHERE rowid = ?", (rowid,))
        await db.commit()
