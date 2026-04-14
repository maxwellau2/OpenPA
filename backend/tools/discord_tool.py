"""Discord tools. Credentials per-user from DB.

Stored credentials include:
- bot_token: for API calls
- guild_id: the server the user authorized the bot for
"""

import httpx
from fastmcp import FastMCP

from tools.credentials import get_creds

mcp = FastMCP("discord")
API_BASE = "https://discord.com/api/v10"


async def _get_discord(user_id: int) -> tuple[dict, str]:
    """Return (headers, guild_id) for the user's Discord connection."""
    creds = await get_creds(user_id, "discord")
    headers = {"Authorization": f"Bot {creds['bot_token']}"}
    guild_id = creds.get("guild_id", "")
    return headers, guild_id


@mcp.tool()
async def list_servers(_user_id: int) -> dict:
    """List the Discord server(s) connected to this user's account. Call this first to get server and channel info.

    Args:
        _user_id: User ID (injected automatically)
    """
    headers, guild_id = await _get_discord(_user_id)

    if not guild_id:
        return {"error": "No Discord server connected. Reconnect Discord in Settings."}

    # Get guild info
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/guilds/{guild_id}", headers=headers)
        resp.raise_for_status()
        guild = resp.json()

        # Also get channels
        ch_resp = await client.get(
            f"{API_BASE}/guilds/{guild_id}/channels", headers=headers
        )
        ch_resp.raise_for_status()
        channels = ch_resp.json()

    text_channels = [
        {"id": c["id"], "name": c["name"]}
        for c in channels
        if c["type"] == 0  # text channels only
    ]

    return {
        "server": {"id": guild["id"], "name": guild["name"]},
        "channels": text_channels,
    }


@mcp.tool()
async def list_channels(_user_id: int, guild_id: str = "") -> dict:
    """List channels in a Discord server. If no guild_id is provided, uses the connected server.

    Args:
        _user_id: User ID (injected automatically)
        guild_id: Discord server/guild ID (optional — defaults to connected server)
    """
    headers, default_guild = await _get_discord(_user_id)
    gid = guild_id or default_guild

    if not gid:
        return {
            "error": "No guild_id provided and no server connected. Reconnect Discord in Settings."
        }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/guilds/{gid}/channels", headers=headers)
        resp.raise_for_status()
        channels = resp.json()

    return {
        "channels": [
            {"id": c["id"], "name": c["name"], "type": c["type"]}
            for c in channels
            if c["type"] in (0, 2, 5)
        ]
    }


@mcp.tool()
async def send_message(
    _user_id: int, channel_name: str = "", channel_id: str = "", content: str = ""
) -> dict:
    """Send a message to a Discord channel. You can specify either channel_name or channel_id.
    If channel_name is given, it will look up the channel ID from the connected server.

    Args:
        _user_id: User ID (injected automatically)
        channel_name: Channel name (e.g. 'general') — will auto-resolve to ID
        channel_id: Discord channel ID (use this if you already have it)
        content: Message content
    """
    headers, guild_id = await _get_discord(_user_id)

    # Resolve channel name to ID if needed
    if channel_name and not channel_id:
        if not guild_id:
            return {
                "error": "No server connected. Provide channel_id directly or reconnect Discord."
            }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{API_BASE}/guilds/{guild_id}/channels", headers=headers
            )
            resp.raise_for_status()
            channels = resp.json()
        for c in channels:
            if c["name"].lower() == channel_name.lower().strip("#"):
                channel_id = c["id"]
                break
        if not channel_id:
            return {
                "error": f"Channel '{channel_name}' not found. Available: {[c['name'] for c in channels if c['type'] == 0]}"
            }

    if not channel_id:
        return {"error": "Provide either channel_name or channel_id."}

    # Discord has a 2000 char limit — split long messages
    chunks = [content[i : i + 1990] for i in range(0, len(content), 1990)]
    sent_ids = []
    async with httpx.AsyncClient() as client:
        for chunk in chunks:
            resp = await client.post(
                f"{API_BASE}/channels/{channel_id}/messages",
                headers=headers,
                json={"content": chunk},
            )
            resp.raise_for_status()
            sent_ids.append(resp.json()["id"])
    return {
        "message_ids": sent_ids,
        "status": "sent",
        "parts": len(chunks),
        "channel_id": channel_id,
    }


@mcp.tool()
async def read_messages(
    _user_id: int, channel_name: str = "", channel_id: str = "", limit: int = 20
) -> dict:
    """Read recent messages from a Discord channel. You can specify either channel_name or channel_id.

    Args:
        _user_id: User ID (injected automatically)
        channel_name: Channel name (e.g. 'general') — will auto-resolve to ID
        channel_id: Discord channel ID (use this if you already have it)
        limit: Number of messages to fetch
    """
    headers, guild_id = await _get_discord(_user_id)

    # Resolve channel name to ID if needed
    if channel_name and not channel_id:
        if not guild_id:
            return {
                "error": "No server connected. Provide channel_id directly or reconnect Discord."
            }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{API_BASE}/guilds/{guild_id}/channels", headers=headers
            )
            resp.raise_for_status()
            channels = resp.json()
        for c in channels:
            if c["name"].lower() == channel_name.lower().strip("#"):
                channel_id = c["id"]
                break
        if not channel_id:
            return {"error": f"Channel '{channel_name}' not found."}

    if not channel_id:
        return {"error": "Provide either channel_name or channel_id."}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/channels/{channel_id}/messages",
            headers=headers,
            params={"limit": limit},
        )
        resp.raise_for_status()
        messages = resp.json()

    return {
        "messages": [
            {
                "id": m["id"],
                "author": m["author"]["username"],
                "content": m["content"],
                "timestamp": m["timestamp"],
            }
            for m in messages
        ]
    }
