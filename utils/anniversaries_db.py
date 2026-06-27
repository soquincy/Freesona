# utils/anniversaries_db.py: Generic anniversary tracking DB for Freesona.
# Stores user-claimed anniversary entries with optional calendar sync support.
# Compatible with cogs/fun/albums.py and any future anniversary-type features.

from __future__ import annotations

import os
import aiosqlite

from datetime import datetime, date, timezone

DB_PATH = os.environ.get("ANNIVERSARIES_FILE_PATH", "anniversaries.db")


async def init_db() -> None:
    """Create the anniversaries table if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS anniversaries (
                id            TEXT PRIMARY KEY,
                guild_id      INTEGER NOT NULL,
                user_id       INTEGER NOT NULL,
                title         TEXT NOT NULL,
                subtitle      TEXT NOT NULL,
                anniversary_date TEXT NOT NULL,
                thumbnail_url TEXT,
                reference_url TEXT,
                calendar_event_id TEXT,
                claimed_at    TEXT NOT NULL
            )
        """)
        await db.commit()


async def insert_entry(data: dict) -> None:
    """
    Insert a new anniversary entry.
    Expected keys: id, guild_id, user_id, title, subtitle,
                   anniversary_date (YYYY-MM-DD), thumbnail_url,
                   reference_url, calendar_event_id
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO anniversaries
                (id, guild_id, user_id, title, subtitle, anniversary_date,
                 thumbnail_url, reference_url, calendar_event_id, claimed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["id"], data["guild_id"], data["user_id"],
            data["title"], data["subtitle"], data["anniversary_date"],
            data.get("thumbnail_url"), data.get("reference_url"),
            data.get("calendar_event_id"),
            datetime.now(timezone.utc).isoformat(),
        ))
        await db.commit()


async def update_calendar_event_id(entry_id: str, calendar_event_id: str) -> None:
    """Update the calendar_event_id for an entry after successful calendar sync."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE anniversaries SET calendar_event_id = ? WHERE id = ?",
            (calendar_event_id, entry_id),
        )
        await db.commit()


async def update_thumbnail(entry_id: str, thumbnail_url: str, reference_url: str | None) -> None:
    """Update thumbnail and reference URL for an entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE anniversaries SET thumbnail_url = ?, reference_url = ? WHERE id = ?",
            (thumbnail_url, reference_url, entry_id),
        )
        await db.commit()


async def get_user_entries(guild_id: int, user_id: int) -> list[dict]:
    """Get all anniversary entries claimed by a user in a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM anniversaries WHERE guild_id = ? AND user_id = ? ORDER BY claimed_at DESC",
            (guild_id, user_id),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_entry(entry_id: str) -> dict | None:
    """Delete an entry by ID. Returns the deleted row or None if not found."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM anniversaries WHERE id = ?", (entry_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        entry = dict(row)
        await db.execute("DELETE FROM anniversaries WHERE id = ?", (entry_id,))
        await db.commit()
    return entry


async def get_todays_entries(guild_id: int, today: date) -> list[dict]:
    """Get all entries whose anniversary falls on today's MM-DD."""
    month_day = today.strftime("%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM anniversaries
               WHERE guild_id = ?
               AND substr(anniversary_date, 6, 5) = ?""",
            (guild_id, month_day),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_entries_on_date(guild_id: int, month_day: str) -> list[dict]:
    """
    Get all entries with an anniversary on a specific MM-DD.
    month_day format: 'MM-DD'
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM anniversaries
               WHERE guild_id = ?
               AND substr(anniversary_date, 6, 5) = ?
               ORDER BY anniversary_date ASC""",
            (guild_id, month_day),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def check_duplicate(guild_id: int, title: str, subtitle: str) -> dict | None:
    """
    Check if a title+subtitle combination is already claimed in a guild.
    Case-insensitive.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM anniversaries
               WHERE guild_id = ?
               AND LOWER(title) = LOWER(?)
               AND LOWER(subtitle) = LOWER(?)""",
            (guild_id, title, subtitle),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def get_entries_missing_calendar(guild_id: int | None = None) -> list[dict]:
    """Get all entries with no calendar_event_id (for sync operations)."""
    sql = "SELECT * FROM anniversaries WHERE calendar_event_id IS NULL"
    params: list = []
    if guild_id is not None:
        sql += " AND guild_id = ?"
        params.append(guild_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_entries_missing_thumbnail(guild_id: int | None = None) -> list[dict]:
    """Get all entries with no thumbnail_url (for cover sync operations)."""
    sql = "SELECT * FROM anniversaries WHERE thumbnail_url IS NULL OR thumbnail_url = ''"
    params: list = []
    if guild_id is not None:
        sql += " AND guild_id = ?"
        params.append(guild_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def search_entries(guild_id: int, query: str | None, user_id: int | None) -> list[dict]:
    """Search entries by title/subtitle and/or user."""
    sql = "SELECT * FROM anniversaries WHERE guild_id = ?"
    params: list = [guild_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    if query:
        sql += " AND (title LIKE ? OR subtitle LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    sql += " ORDER BY claimed_at DESC"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]