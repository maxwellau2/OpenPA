"""User memory and preferences tools."""

import json

import aiosqlite

from config import config
from fastmcp import FastMCP

mcp = FastMCP("memory")


@mcp.tool()
async def get_preferences(_user_id: int, category: str = "") -> dict:
    """Get user preferences, optionally filtered by category.

    Args:
        _user_id: User ID (injected automatically)
        category: Filter by category (e.g. 'music', 'work', 'general')
    """
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        if category:
            cursor = await db.execute(
                "SELECT key, value, category FROM preferences WHERE user_id = ? AND category = ?",
                (_user_id, category),
            )
        else:
            cursor = await db.execute(
                "SELECT key, value, category FROM preferences WHERE user_id = ?", (_user_id,)
            )
        rows = await cursor.fetchall()
        return {"preferences": [{k: row[k] for k in row.keys()} for row in rows]}


@mcp.tool()
async def set_preference(_user_id: int, key: str, value: str, category: str = "general") -> dict:
    """Store or update a user preference.

    Args:
        _user_id: User ID (injected automatically)
        key: Preference key (e.g. 'favorite_music_genre')
        value: Preference value
        category: Category for grouping
    """
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO preferences (user_id, key, value, category, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id, key) DO UPDATE SET value=?, category=?, updated_at=CURRENT_TIMESTAMP""",
            (_user_id, key, value, category, value, category),
        )
        await db.commit()
    return {"status": "saved", "key": key, "value": value}


@mcp.tool()
async def search_history(_user_id: int, query: str, limit: int = 10) -> dict:
    """Search past conversation history.

    Args:
        _user_id: User ID (injected automatically)
        query: Search query
        limit: Max results to return
    """
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content, created_at FROM conversation_history WHERE user_id = ? AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
            (_user_id, f"%{query}%", limit),
        )
        rows = await cursor.fetchall()
        return {"results": [{k: row[k] for k in row.keys()} for row in rows]}


@mcp.tool()
async def save_note(_user_id: int, content: str, tags: str = "") -> dict:
    """Save a note for later reference.

    Args:
        _user_id: User ID (injected automatically)
        content: Note content
        tags: Comma-separated tags
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "INSERT INTO notes (user_id, content, tags) VALUES (?, ?, ?)",
            (_user_id, content, json.dumps(tag_list)),
        )
        await db.commit()
        return {"status": "saved", "note_id": cursor.lastrowid}
