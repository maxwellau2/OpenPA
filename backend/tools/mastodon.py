"""Mastodon tools — fetch timelines, post statuses, analyze trends, and search."""

import httpx
from fastmcp import FastMCP

from tools.credentials import get_creds

mcp = FastMCP("mastodon")


async def _headers(user_id: int) -> dict:
    creds = await get_creds(user_id, "mastodon")
    return {"Authorization": f"Bearer {creds['token']}"}


async def _base_url(user_id: int) -> str:
    creds = await get_creds(user_id, "mastodon")
    return creds["instance_url"].rstrip("/")


@mcp.tool()
async def get_home_timeline(_user_id: int, limit: int = 20) -> dict:
    """Fetch the user's home timeline (posts from people they follow).

    Args:
        _user_id: User ID (injected automatically)
        limit: Number of posts to fetch (max 40)
    """
    headers = await _headers(_user_id)
    base = await _base_url(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/api/v1/timelines/home",
            headers=headers,
            params={"limit": min(limit, 40)},
        )
        resp.raise_for_status()
        statuses = resp.json()
    return {"posts": [_format_status(s) for s in statuses]}


@mcp.tool()
async def get_public_timeline(
    _user_id: int, local: bool = False, limit: int = 20
) -> dict:
    """Fetch the public or local timeline to see what's trending on the instance.

    Args:
        _user_id: User ID (injected automatically)
        local: If True, only show posts from the local instance
        limit: Number of posts to fetch (max 40)
    """
    headers = await _headers(_user_id)
    base = await _base_url(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/api/v1/timelines/public",
            headers=headers,
            params={"local": str(local).lower(), "limit": min(limit, 40)},
        )
        resp.raise_for_status()
        statuses = resp.json()
    return {"posts": [_format_status(s) for s in statuses]}


@mcp.tool()
async def get_trending_tags(_user_id: int, limit: int = 10) -> dict:
    """Get currently trending hashtags on the instance.

    Args:
        _user_id: User ID (injected automatically)
        limit: Number of trending tags to fetch
    """
    headers = await _headers(_user_id)
    base = await _base_url(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/api/v1/trends/tags",
            headers=headers,
            params={"limit": limit},
        )
        resp.raise_for_status()
        tags = resp.json()
    return {
        "trending_tags": [
            {
                "name": t["name"],
                "url": t.get("url", ""),
                "uses_today": t.get("history", [{}])[0].get("uses", "0")
                if t.get("history")
                else "0",
                "accounts_today": t.get("history", [{}])[0].get("accounts", "0")
                if t.get("history")
                else "0",
            }
            for t in tags
        ]
    }


@mcp.tool()
async def get_trending_statuses(_user_id: int, limit: int = 10) -> dict:
    """Get currently trending posts on the instance.

    Args:
        _user_id: User ID (injected automatically)
        limit: Number of trending posts to fetch
    """
    headers = await _headers(_user_id)
    base = await _base_url(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/api/v1/trends/statuses",
            headers=headers,
            params={"limit": limit},
        )
        resp.raise_for_status()
        statuses = resp.json()
    return {"trending_posts": [_format_status(s) for s in statuses]}


@mcp.tool()
async def search_posts(_user_id: int, query: str, limit: int = 20) -> dict:
    """Search for posts, accounts, or hashtags on Mastodon.

    Args:
        _user_id: User ID (injected automatically)
        query: Search query
        limit: Max results to return
    """
    headers = await _headers(_user_id)
    base = await _base_url(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/api/v2/search",
            headers=headers,
            params={"q": query, "limit": limit, "type": "statuses"},
        )
        resp.raise_for_status()
        data = resp.json()
    return {"posts": [_format_status(s) for s in data.get("statuses", [])]}


@mcp.tool()
async def get_hashtag_timeline(_user_id: int, hashtag: str, limit: int = 20) -> dict:
    """Fetch recent posts for a specific hashtag — useful for analyzing trends around a topic.

    Args:
        _user_id: User ID (injected automatically)
        hashtag: The hashtag to look up (without the # symbol)
        limit: Number of posts to fetch
    """
    headers = await _headers(_user_id)
    base = await _base_url(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/api/v1/timelines/tag/{hashtag}",
            headers=headers,
            params={"limit": min(limit, 40)},
        )
        resp.raise_for_status()
        statuses = resp.json()
    return {"posts": [_format_status(s) for s in statuses]}


@mcp.tool()
async def post_status(
    _user_id: int, status: str, visibility: str = "public", spoiler_text: str = ""
) -> dict:
    """Post a new status (toot) to Mastodon.

    Args:
        _user_id: User ID (injected automatically)
        status: The text content of the post
        visibility: One of: public, unlisted, private, direct
        spoiler_text: Optional content warning text
    """
    headers = await _headers(_user_id)
    base = await _base_url(_user_id)
    payload = {"status": status, "visibility": visibility}
    if spoiler_text:
        payload["spoiler_text"] = spoiler_text

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base}/api/v1/statuses", headers=headers, json=payload
        )
        resp.raise_for_status()
        status = resp.json()
    return {
        "id": status["id"],
        "url": status.get("url", ""),
        "created_at": status["created_at"],
    }


@mcp.tool()
async def get_notifications(_user_id: int, limit: int = 15) -> dict:
    """Get recent Mastodon notifications (mentions, boosts, favourites, follows).

    Args:
        _user_id: User ID (injected automatically)
        limit: Number of notifications to fetch
    """
    headers = await _headers(_user_id)
    base = await _base_url(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/api/v1/notifications",
            headers=headers,
            params={"limit": limit},
        )
        resp.raise_for_status()
        notifs = resp.json()
    return {
        "notifications": [
            {
                "type": n["type"],
                "created_at": n["created_at"],
                "account": n["account"]["acct"],
                "status_content": _strip_html(n["status"]["content"])[:200]
                if n.get("status")
                else None,
            }
            for n in notifs
        ]
    }


@mcp.tool()
async def get_account_info(_user_id: int) -> dict:
    """Get the authenticated user's Mastodon profile information.

    Args:
        _user_id: User ID (injected automatically)
    """
    headers = await _headers(_user_id)
    base = await _base_url(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/api/v1/accounts/verify_credentials", headers=headers
        )
        resp.raise_for_status()
        acct = resp.json()
    return {
        "username": acct["username"],
        "display_name": acct["display_name"],
        "acct": acct["acct"],
        "url": acct["url"],
        "followers": acct["followers_count"],
        "following": acct["following_count"],
        "statuses": acct["statuses_count"],
        "bio": _strip_html(acct.get("note", "")),
    }


def _format_status(s: dict) -> dict:
    reblog = s.get("reblog")
    source = reblog or s
    return {
        "id": s["id"],
        "author": source["account"]["acct"],
        "content": _strip_html(source["content"])[:500],
        "created_at": source["created_at"],
        "boosts": source["reblogs_count"],
        "favourites": source["favourites_count"],
        "replies": source["replies_count"],
        "url": source.get("url", ""),
        "tags": [t["name"] for t in source.get("tags", [])],
        "is_reblog": reblog is not None,
    }


def _strip_html(html: str) -> str:
    """Minimal HTML tag stripping for Mastodon content."""
    import re

    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</p><p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return text.strip()
