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
async def get_recent_conversations(_user_id: int, count: int = 1) -> dict:
    """Get messages from the user's most recent conversations. Use this when the user asks
    about what they said last chat, their previous conversation, or recent chat history.

    Args:
        _user_id: User ID (injected automatically)
        count: Number of recent conversations to retrieve (default 1 = last conversation)
    """
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        # Get the most recent conversation(s), excluding the current one (the one being created now)
        cursor = await db.execute(
            "SELECT id, title, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET 1",
            (_user_id, count),
        )
        convs = await cursor.fetchall()
        if not convs:
            return {"conversations": [], "message": "No previous conversations found."}

        result = []
        for conv in convs:
            cursor = await db.execute(
                "SELECT role, content, created_at FROM conversation_history WHERE user_id = ? AND conversation_id = ? ORDER BY created_at",
                (_user_id, conv["id"]),
            )
            messages = await cursor.fetchall()
            result.append({
                "conversation_id": conv["id"],
                "title": conv["title"],
                "updated_at": conv["updated_at"],
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            })
        return {"conversations": result}


@mcp.tool()
async def search_history(_user_id: int, query: str, limit: int = 10) -> dict:
    """Search past conversation history using semantic search. Finds messages by meaning, not just keywords.

    Args:
        _user_id: User ID (injected automatically)
        query: Search query (semantic — searches by meaning)
        limit: Max results to return
    """
    from services.rag import search_conversation_history

    try:
        results = await search_conversation_history(_user_id, query, top_k=limit)
        if results:
            return {"results": results}
    except Exception:
        pass

    # Fallback to SQL keyword search if RAG fails
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content, created_at FROM conversation_history WHERE user_id = ? AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
            (_user_id, f"%{query}%", limit),
        )
        rows = await cursor.fetchall()
        return {"results": [{k: row[k] for k in row.keys()} for row in rows]}


@mcp.tool()
async def remember_about_user(_user_id: int, content: str, category: str = "general") -> dict:
    """Save a long-term memory about the user. Use this to remember personality traits,
    preferences, habits, interests, communication style, or any personal details the user
    shares. These memories persist across conversations and help you personalize future interactions.

    Args:
        _user_id: User ID (injected automatically)
        content: What to remember (e.g. 'User prefers concise answers', 'User is a cloud engineering student')
        category: Category like 'personality', 'interests', 'work', 'communication', 'general'
    """
    from services.rag import store_memory

    async with aiosqlite.connect(config.db_path) as db:
        # Check for duplicate/similar memories to avoid redundancy
        cursor = await db.execute(
            "SELECT id, content FROM user_memories WHERE user_id = ? AND category = ?",
            (_user_id, category),
        )
        existing = await cursor.fetchall()
        # Simple dedup: if content is very similar to existing, update instead
        for row in existing:
            if content.lower().strip() in row[1].lower() or row[1].lower() in content.lower().strip():
                await db.execute(
                    "UPDATE user_memories SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (content, row[0]),
                )
                await db.commit()
                # Update embedding in ChromaDB
                await store_memory(_user_id, row[0], content, category)
                return {"status": "updated", "memory_id": row[0], "content": content}

        cursor = await db.execute(
            "INSERT INTO user_memories (user_id, content, category) VALUES (?, ?, ?)",
            (_user_id, content, category),
        )
        await db.commit()
        memory_id = cursor.lastrowid
        # Store embedding in ChromaDB
        await store_memory(_user_id, memory_id, content, category)
        return {"status": "saved", "memory_id": memory_id, "content": content}


@mcp.tool()
async def get_user_memories(_user_id: int, category: str = "") -> dict:
    """Retrieve all long-term memories about the user.

    Args:
        _user_id: User ID (injected automatically)
        category: Filter by category (optional)
    """
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        if category:
            cursor = await db.execute(
                "SELECT id, content, category, created_at FROM user_memories WHERE user_id = ? AND category = ? ORDER BY updated_at DESC",
                (_user_id, category),
            )
        else:
            cursor = await db.execute(
                "SELECT id, content, category, created_at FROM user_memories WHERE user_id = ? ORDER BY updated_at DESC",
                (_user_id,),
            )
        rows = await cursor.fetchall()
        return {"memories": [{k: row[k] for k in row.keys()} for row in rows]}


@mcp.tool()
async def forget_about_user(_user_id: int, memory_id: int) -> dict:
    """Delete a specific memory about the user.

    Args:
        _user_id: User ID (injected automatically)
        memory_id: The ID of the memory to delete
    """
    from services.rag import delete_memory

    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "DELETE FROM user_memories WHERE id = ? AND user_id = ?",
            (memory_id, _user_id),
        )
        await db.commit()
    # Remove from ChromaDB
    await delete_memory(_user_id, memory_id)
    return {"status": "forgotten", "memory_id": memory_id}


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
