"""
database.py — Dual-mode database layer
• DATABASE_URL set → PostgreSQL (asyncpg)  ← Heroku / production
• DATABASE_URL not set → SQLite (aiosqlite) ← local / testing
"""
import os
import asyncio
import datetime
import logging

import aiosqlite
from config import DB_NAME

logger = logging.getLogger(__name__)

# ─── Backend detection ────────────────────────────────────────────────────────
_DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Heroku gives postgres:// but asyncpg needs postgresql://
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

USE_PG = bool(_DATABASE_URL)

if USE_PG:
    try:
        import asyncpg
        logger.info("DB backend: PostgreSQL (asyncpg)")
    except ImportError:
        logger.error("asyncpg not installed — falling back to SQLite")
        USE_PG = False
else:
    logger.info("DB backend: SQLite (aiosqlite)")

# ─── PostgreSQL connection pool ───────────────────────────────────────────────
_pg_pool = None

async def _get_pool():
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = await asyncpg.create_pool(_DATABASE_URL, min_size=1, max_size=5)
    return _pg_pool


# ═══════════════════════════════════════════════════════════════════════════════
# ─── INIT DB ──────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    joined_date TEXT,
                    plan TEXT DEFAULT 'FREE',
                    expiry TEXT DEFAULT 'N/A',
                    referred_by BIGINT,
                    referral_count INTEGER DEFAULT 0,
                    total_attacks INTEGER DEFAULT 0,
                    success_attacks INTEGER DEFAULT 0,
                    daily_limit INTEGER DEFAULT 2,
                    today_attacks INTEGER DEFAULT 0,
                    last_attack_date TEXT,
                    channel_verified INTEGER DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS redeem_codes (
                    code TEXT PRIMARY KEY,
                    plan_type TEXT,
                    duration_days INTEGER,
                    is_used INTEGER DEFAULT 0,
                    used_by BIGINT DEFAULT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS owners (
                    user_id BIGINT PRIMARY KEY,
                    added_date TEXT,
                    added_by BIGINT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            # Migration: add channel_verified if missing (safe on PG too)
            try:
                await conn.execute(
                    "ALTER TABLE users ADD COLUMN channel_verified INTEGER DEFAULT 0"
                )
            except Exception:
                pass
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    joined_date TEXT,
                    plan TEXT DEFAULT 'FREE',
                    expiry TEXT DEFAULT 'N/A',
                    referred_by INTEGER,
                    referral_count INTEGER DEFAULT 0,
                    total_attacks INTEGER DEFAULT 0,
                    success_attacks INTEGER DEFAULT 0,
                    daily_limit INTEGER DEFAULT 2,
                    today_attacks INTEGER DEFAULT 0,
                    last_attack_date TEXT,
                    channel_verified INTEGER DEFAULT 0
                )
            """)
            try:
                await db.execute(
                    "ALTER TABLE users ADD COLUMN channel_verified INTEGER DEFAULT 0"
                )
                await db.commit()
            except aiosqlite.OperationalError:
                pass
            await db.execute("""
                CREATE TABLE IF NOT EXISTS redeem_codes (
                    code TEXT PRIMARY KEY,
                    plan_type TEXT,
                    duration_days INTEGER,
                    is_used INTEGER DEFAULT 0,
                    used_by INTEGER DEFAULT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS owners (
                    user_id INTEGER PRIMARY KEY,
                    added_date TEXT,
                    added_by INTEGER
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# ─── OWNERS ───────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

async def add_owner(user_id: int, added_by: int) -> bool:
    added_date = datetime.date.today().isoformat()
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM owners WHERE user_id = $1", user_id
            )
            if row:
                return False
            await conn.execute(
                "INSERT INTO owners (user_id, added_date, added_by) VALUES ($1, $2, $3)",
                user_id, added_date, added_by
            )
            return True
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT user_id FROM owners WHERE user_id = ?", (user_id,)
            )
            if await cur.fetchone():
                return False
            await db.execute(
                "INSERT INTO owners (user_id, added_date, added_by) VALUES (?, ?, ?)",
                (user_id, added_date, added_by)
            )
            await db.commit()
            return True


async def remove_owner(user_id: int) -> bool:
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM owners WHERE user_id = $1", user_id
            )
            return result.split()[-1] != "0"
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "DELETE FROM owners WHERE user_id = ?", (user_id,)
            )
            await db.commit()
            return cur.rowcount > 0


async def get_owners() -> list:
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, added_date FROM owners ORDER BY added_date"
            )
            return [(r["user_id"], r["added_date"]) for r in rows]
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT user_id, added_date FROM owners ORDER BY added_date"
            ) as cur:
                return await cur.fetchall()


async def is_secondary_owner(user_id: int) -> bool:
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM owners WHERE user_id = $1", user_id
            )
            return row is not None
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT user_id FROM owners WHERE user_id = ?", (user_id,)
            ) as cur:
                return (await cur.fetchone()) is not None


# ═══════════════════════════════════════════════════════════════════════════════
# ─── SETTINGS ─────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

async def set_setting(key: str, value: str):
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO settings (key, value) VALUES ($1, $2)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                key, value
            )
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
            await db.commit()


async def get_setting(key: str) -> str | None:
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = $1", key
            )
            return row["value"] if row else None
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None


# ═══════════════════════════════════════════════════════════════════════════════
# ─── CHANNEL VERIFICATION ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

async def mark_channel_verified(user_id: int):
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET channel_verified = 1 WHERE user_id = $1", user_id
            )
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET channel_verified = 1 WHERE user_id = ?", (user_id,)
            )
            await db.commit()


async def is_channel_verified(user_id: int) -> bool:
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT channel_verified FROM users WHERE user_id = $1", user_id
            )
            return bool(row and row["channel_verified"])
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(
                "SELECT channel_verified FROM users WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
                return bool(row and row[0])


# ═══════════════════════════════════════════════════════════════════════════════
# ─── USERS ────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

async def get_user(user_id):
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1", user_id
            )
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cur:
                return await cur.fetchone()


async def get_all_users():
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM users ORDER BY joined_date DESC"
            )
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users ORDER BY joined_date DESC"
            ) as cur:
                return await cur.fetchall()


async def add_user(user_id, username, referred_by=None):
    joined_date = datetime.date.today().isoformat()
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT user_id, username FROM users WHERE user_id = $1", user_id
            )
            if not existing:
                await conn.execute(
                    """INSERT INTO users (user_id, username, joined_date, referred_by)
                       VALUES ($1, $2, $3, $4)""",
                    user_id, username, joined_date, referred_by
                )
                if referred_by:
                    await conn.execute(
                        """UPDATE users
                           SET referral_count = referral_count + 1,
                               daily_limit = daily_limit + 1
                           WHERE user_id = $1""",
                        referred_by
                    )
                return True
            else:
                if existing["username"] != username:
                    await conn.execute(
                        "UPDATE users SET username = $1 WHERE user_id = $2",
                        username, user_id
                    )
                return False
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            user = await get_user(user_id)
            if not user:
                await db.execute(
                    "INSERT INTO users (user_id, username, joined_date, referred_by) VALUES (?, ?, ?, ?)",
                    (user_id, username, joined_date, referred_by)
                )
                if referred_by:
                    await db.execute(
                        "UPDATE users SET referral_count = referral_count + 1, daily_limit = daily_limit + 1 WHERE user_id = ?",
                        (referred_by,)
                    )
                await db.commit()
                return True
            else:
                if user["username"] != username:
                    await db.execute(
                        "UPDATE users SET username = ? WHERE user_id = ?",
                        (username, user_id)
                    )
                    await db.commit()
                return False


async def update_stats(user_id, rounds=1, success=True):
    today = datetime.date.today().isoformat()
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT today_attacks, last_attack_date FROM users WHERE user_id = $1", user_id
            )
            today_attacks = user["today_attacks"] if user else 0
            if user and user["last_attack_date"] != today:
                today_attacks = 0
            await conn.execute(
                """UPDATE users
                   SET total_attacks    = total_attacks + $1,
                       success_attacks  = success_attacks + $2,
                       today_attacks    = $3,
                       last_attack_date = $4
                   WHERE user_id = $5""",
                rounds, 1 if success else 0,
                today_attacks + rounds, today, user_id
            )
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            user = await get_user(user_id)
            today_attacks = user["today_attacks"] if user else 0
            if user and user["last_attack_date"] != today:
                today_attacks = 0
            await db.execute(
                """UPDATE users
                   SET total_attacks    = total_attacks + ?,
                       success_attacks  = success_attacks + ?,
                       today_attacks    = ?,
                       last_attack_date = ?
                   WHERE user_id = ?""",
                (rounds, 1 if success else 0, today_attacks + rounds, today, user_id)
            )
            await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# ─── REDEEM CODES ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

async def add_redeem_code(code: str, plan_type: str, duration_days: int):
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO redeem_codes (code, plan_type, duration_days, is_used)
                   VALUES ($1, $2, $3, 0)
                   ON CONFLICT (code) DO UPDATE
                       SET plan_type = EXCLUDED.plan_type,
                           duration_days = EXCLUDED.duration_days,
                           is_used = 0""",
                code, plan_type, duration_days
            )
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO redeem_codes (code, plan_type, duration_days, is_used) VALUES (?, ?, ?, 0)",
                (code, plan_type, duration_days)
            )
            await db.commit()


async def gift_premium_to_user(user_id: int, plan_type: str, duration_days: int) -> bool:
    expiry    = (datetime.date.today() + datetime.timedelta(days=duration_days)).isoformat()
    new_limit = 200 if plan_type == "VIP" else (50 if plan_type == "PRO" else 10)
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT user_id FROM users WHERE user_id = $1", user_id
            )
            if not user:
                return False
            await conn.execute(
                "UPDATE users SET plan = $1, expiry = $2, daily_limit = $3 WHERE user_id = $4",
                plan_type, expiry, new_limit, user_id
            )
            return True
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            user = await get_user(user_id)
            if not user:
                return False
            await db.execute(
                "UPDATE users SET plan = ?, expiry = ?, daily_limit = ? WHERE user_id = ?",
                (plan_type, expiry, new_limit, user_id)
            )
            await db.commit()
            return True


async def use_redeem_code(code: str, user_id: int):
    if USE_PG:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM redeem_codes WHERE code = $1", code
            )
            if not row:
                return "not_found"
            if row["is_used"]:
                return "already_used"
            already = await conn.fetchrow(
                "SELECT code FROM redeem_codes WHERE used_by = $1", user_id
            )
            if already:
                return "already_redeemed"

            plan_type     = row["plan_type"]
            duration_days = row["duration_days"]
            expiry        = (datetime.date.today() + datetime.timedelta(days=duration_days)).isoformat()

            await conn.execute(
                "UPDATE users SET plan = $1, expiry = $2, daily_limit = daily_limit + 5 WHERE user_id = $3",
                plan_type, expiry, user_id
            )
            await conn.execute(
                "UPDATE redeem_codes SET is_used = 1, used_by = $1 WHERE code = $2",
                user_id, code
            )
            return (plan_type, duration_days)
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM redeem_codes WHERE code = ?", (code,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return "not_found"
            if row["is_used"]:
                return "already_used"
            async with db.execute(
                "SELECT code FROM redeem_codes WHERE used_by = ?", (user_id,)
            ) as cur:
                if await cur.fetchone():
                    return "already_redeemed"

            plan_type     = row["plan_type"]
            duration_days = row["duration_days"]
            expiry        = (datetime.date.today() + datetime.timedelta(days=duration_days)).isoformat()

            await db.execute(
                "UPDATE users SET plan = ?, expiry = ?, daily_limit = daily_limit + 5 WHERE user_id = ?",
                (plan_type, expiry, user_id)
            )
            await db.execute(
                "UPDATE redeem_codes SET is_used = 1, used_by = ? WHERE code = ?",
                (user_id, code)
            )
            await db.commit()
            return (plan_type, duration_days)
