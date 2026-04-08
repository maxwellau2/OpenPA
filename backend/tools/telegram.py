"""Telegram tools — self-resolving. Searches contacts/chats to find recipients automatically.

Uses Telethon (MTProto User API) so messages come from YOU, not a bot.
"""

from fastmcp import FastMCP
from tools.credentials import get_creds

mcp = FastMCP("telegram")


async def _get_client(user_id: int):
    """Get an authenticated Telethon client for this user."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    creds = await get_creds(user_id, "telegram")
    client = TelegramClient(StringSession(creds.get("session_string", "")), int(creds["api_id"]), creds["api_hash"])
    await client.connect()
    return client


async def _resolve_recipient(client, name: str) -> tuple:
    """Find a chat/contact by name, username, or phone. Returns (entity, display_name)."""
    # If it looks like a username or phone, use directly
    if name.startswith("@") or name.startswith("+"):
        entity = await client.get_entity(name)
        display = getattr(entity, 'first_name', '') or getattr(entity, 'title', '') or name
        return entity, display

    # Search contacts first
    from telethon.tl.functions.contacts import SearchRequest
    result = await client(SearchRequest(q=name, limit=5))
    if result.users:
        user = result.users[0]
        return user, f"{user.first_name or ''} {user.last_name or ''}".strip()

    # Search dialogs (chats/groups)
    dialogs = await client.get_dialogs(limit=50)
    name_lower = name.lower()
    for d in dialogs:
        if name_lower in d.name.lower():
            return d.entity, d.name

    # Last resort — try as-is
    entity = await client.get_entity(name)
    display = getattr(entity, 'first_name', '') or getattr(entity, 'title', '') or name
    return entity, display


@mcp.tool()
async def search_contacts(_user_id: int, query: str) -> dict:
    """Search your Telegram contacts and chats by name. Call this to find who to message.

    Args:
        _user_id: User ID (injected automatically)
        query: Name to search for (partial match works)
    """
    client = await _get_client(_user_id)
    try:
        results = []

        # Search contacts
        from telethon.tl.functions.contacts import SearchRequest
        contact_result = await client(SearchRequest(q=query, limit=10))
        for user in contact_result.users:
            name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            results.append({
                "name": name,
                "username": f"@{user.username}" if user.username else "",
                "id": user.id,
                "type": "user",
            })

        # Also search dialogs
        dialogs = await client.get_dialogs(limit=50)
        query_lower = query.lower()
        for d in dialogs:
            if query_lower in d.name.lower():
                already = any(r["id"] == d.id for r in results)
                if not already:
                    results.append({
                        "name": d.name,
                        "username": "",
                        "id": d.id,
                        "type": "group" if d.is_group else "channel" if d.is_channel else "user",
                        "unread_count": d.unread_count,
                    })

        return {"query": query, "results": results}
    finally:
        await client.disconnect()


@mcp.tool()
async def send_message(_user_id: int, to: str, message: str) -> dict:
    """Send a Telegram message from your account. Auto-resolves contact names.
    Just provide a name like "Mom", "John", or a group name — it will find the right chat.

    Args:
        _user_id: User ID (injected automatically)
        to: Recipient — name, username (@john), phone (+65...), or group name
        message: Message text
    """
    client = await _get_client(_user_id)
    try:
        entity, display_name = await _resolve_recipient(client, to)
        result = await client.send_message(entity, message)
        return {"status": "sent", "message_id": result.id, "to": display_name}
    except Exception as e:
        return {"error": f"Could not find '{to}': {e}. Try search_contacts first to find the right name."}
    finally:
        await client.disconnect()


@mcp.tool()
async def list_chats(_user_id: int, limit: int = 20) -> dict:
    """List your recent Telegram chats/conversations.

    Args:
        _user_id: User ID (injected automatically)
        limit: Number of chats to return
    """
    client = await _get_client(_user_id)
    try:
        dialogs = await client.get_dialogs(limit=limit)
        return {"chats": [
            {
                "name": d.name,
                "id": d.id,
                "unread_count": d.unread_count,
                "type": "group" if d.is_group else "channel" if d.is_channel else "user",
            }
            for d in dialogs
        ]}
    finally:
        await client.disconnect()


@mcp.tool()
async def read_messages(_user_id: int, chat: str, limit: int = 20) -> dict:
    """Read recent messages from a Telegram chat. Auto-resolves chat names.

    Args:
        _user_id: User ID (injected automatically)
        chat: Chat name, username, or partial name — auto-resolved
        limit: Number of messages to fetch
    """
    client = await _get_client(_user_id)
    try:
        entity, display_name = await _resolve_recipient(client, chat)
        messages = await client.get_messages(entity, limit=limit)
        return {"chat": display_name, "messages": [
            {
                "id": m.id,
                "sender": getattr(m.sender, 'first_name', '') or getattr(m.sender, 'title', '') if m.sender else "Unknown",
                "text": m.text or "",
                "date": str(m.date),
            }
            for m in messages
            if m.text
        ]}
    except Exception as e:
        return {"error": f"Could not find chat '{chat}': {e}"}
    finally:
        await client.disconnect()
