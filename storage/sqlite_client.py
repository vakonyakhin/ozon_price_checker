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

        # Table for user settings
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                check_interval INTEGER,
                last_check TIMESTAMP
            )
        """)

        # Table for price history
        await db.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                url TEXT,
                price REAL,
                checked_at TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_price_history_url_date ON price_history (url, checked_at)")
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

async def get_users_statistics() -> list[tuple[int, int, Optional[str]]]:
    async with aiosqlite.connect(DB_FILE) as db:
        subqueries = []
        for table in TABLES:
            subqueries.append(f"SELECT user_id, COUNT(*) as cnt, MAX(added_at) as last_added FROM {table} GROUP BY user_id")
        
        union_query = " UNION ALL ".join(subqueries)
        final_query = f"SELECT user_id, SUM(cnt), MAX(last_added) FROM ({union_query}) GROUP BY user_id"
        
        cursor = await db.execute(final_query)
        return await cursor.fetchall()

async def set_user_check_interval(user_id: int, interval_minutes: int):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,))
        if await cursor.fetchone():
            await db.execute("UPDATE user_settings SET check_interval = ? WHERE user_id = ?", (interval_minutes, user_id))
        else:
            await db.execute("INSERT INTO user_settings (user_id, check_interval) VALUES (?, ?)", (user_id, interval_minutes))
        await db.commit()

async def get_user_check_interval(user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT check_interval FROM user_settings WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else None

async def get_all_user_settings() -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT user_id, check_interval, last_check FROM user_settings")
        rows = await cursor.fetchall()
        return {row[0]: {"check_interval": row[1], "last_check": row[2]} for row in rows}

async def update_user_last_check(user_id: int):
    now = datetime.datetime.now()
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,))
        if await cursor.fetchone():
            await db.execute("UPDATE user_settings SET last_check = ? WHERE user_id = ?", (now, user_id))
        else:
            await db.execute("INSERT INTO user_settings (user_id, last_check) VALUES (?, ?)", (user_id, now))
        await db.commit()

async def add_price_history(url: str, price: float):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO price_history (url, price, checked_at) VALUES (?, ?, ?)",
            (url, price, datetime.datetime.now())
        )
        await db.commit()

async def cleanup_old_price_history(days: int = 7):
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM price_history WHERE checked_at < ?", (cutoff,))
        await db.commit()

async def get_url_by_rowid(rowid: int, table: str) -> Optional[str]:
    if table not in TABLES:
        return None
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(f"SELECT url FROM {table} WHERE rowid = ?", (rowid,))
        row = await cursor.fetchone()
        return row[0] if row else None

async def get_price_history(url: str) -> list[tuple[datetime.datetime, float]]:
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(
            "SELECT checked_at, price FROM price_history WHERE url = ? ORDER BY checked_at DESC",
            (url,)
        )
        return await cursor.fetchall()
