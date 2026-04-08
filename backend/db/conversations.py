"""Conversation persistence and compaction."""

import json

import aiosqlite
from loguru import logger

from config import config

COMPACTION_THRESHOLD = 30  # Compact after this many messages


async def get_or_create_conversation(user_id: int, conv_id: int | None, title: str = "New Chat") -> int:
    """Get existing conversation or create a new one."""
    if conv_id:
        return conv_id
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
            (user_id, title[:50]),
        )
        await db.commit()
        return cursor.lastrowid


async def load_messages(user_id: int, conv_id: int) -> list[dict]:
    """Load conversation messages from DB."""
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content FROM conversation_history WHERE user_id = ? AND conversation_id = ? ORDER BY created_at",
            (user_id, conv_id),
        )
        rows = await cursor.fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


async def save_message(user_id: int, conv_id: int, role: str, content: str):
    """Save a single message to the conversation."""
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "INSERT INTO conversation_history (user_id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (user_id, conv_id, role, content),
        )
        await db.commit()


async def update_conversation_title(conv_id: int, title: str):
    """Update the conversation title and timestamp."""
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP, title = ? WHERE id = ?",
            (title[:50], conv_id),
        )
        await db.commit()


async def compact_conversation(user_id: int, conv_id: int, provider) -> bool:
    """Compact a conversation if it exceeds the threshold.

    Summarizes old messages into a single summary message and deletes the originals.
    Returns True if compaction happened.
    """
    messages = await load_messages(user_id, conv_id)

    if len(messages) < COMPACTION_THRESHOLD:
        return False

    logger.info(f"Compacting conversation {conv_id} ({len(messages)} messages)")

    # Keep the last 6 messages (3 exchanges), summarize the rest
    keep_recent = 6
    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]

    # Build text for summarization
    old_text = ""
    for msg in old_messages:
        content = msg["content"][:200]
        old_text += f"{msg['role']}: {content}\n"

    # Ask LLM to summarize
    from llm.base import Message
    summary_messages = [
        Message(role="user", content=f"Summarize this conversation concisely:\n{old_text}")
    ]

    try:
        response = await provider.chat(
            messages=summary_messages,
            tools=None,
            system="Summarize the conversation into a brief paragraph. Include key facts, actions taken, and any pending tasks. Keep it under 200 words.",
        )
        summary = response.content or "Previous conversation context."
    except Exception:
        summary = "Previous conversation context unavailable."

    # Replace messages in DB: delete old, insert summary, keep recent
    async with aiosqlite.connect(config.db_path) as db:
        # Delete all messages for this conversation
        await db.execute(
            "DELETE FROM conversation_history WHERE user_id = ? AND conversation_id = ?",
            (user_id, conv_id),
        )

        # Insert summary as first message
        await db.execute(
            "INSERT INTO conversation_history (user_id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
            (user_id, conv_id, "assistant", f"[Conversation summary: {summary}]"),
        )

        # Re-insert recent messages
        for msg in recent_messages:
            await db.execute(
                "INSERT INTO conversation_history (user_id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
                (user_id, conv_id, msg["role"], msg["content"]),
            )

        await db.commit()

    logger.info(f"Compacted conversation {conv_id}: {len(messages)} → {len(recent_messages) + 1} messages")
    return True
