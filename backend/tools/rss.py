"""RSS feed tools — self-resolving. fetch_feed can accept a name or URL."""

import asyncio

import aiosqlite
import feedparser
import httpx
from fastmcp import FastMCP

from config import config

mcp = FastMCP("rss")

FETCH_TIMEOUT = 10


async def _fetch_and_parse(url: str) -> feedparser.FeedParserDict:
    """Fetch a feed URL asynchronously with httpx, then parse the XML with feedparser."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        return feedparser.parse(resp.text)


async def _resolve_feed_url(user_id: int, name_or_url: str) -> str:
    """If input looks like a URL, return it. Otherwise look up by name in saved feeds."""
    if name_or_url.startswith("http://") or name_or_url.startswith("https://"):
        return name_or_url

    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT url FROM rss_feeds WHERE user_id = ? AND (LOWER(name) LIKE ? OR LOWER(url) LIKE ?)",
            (user_id, f"%{name_or_url.lower()}%", f"%{name_or_url.lower()}%"),
        )
        row = await cursor.fetchone()
        if row:
            return row["url"]

    return name_or_url


@mcp.tool()
async def fetch_feed(_user_id: int, feed: str, max_items: int = 10) -> dict:
    """Fetch and parse an RSS feed. Accepts a URL or a saved feed name.
    Examples: "https://hnrss.org/frontpage" or "Hacker News" or "crypto"

    Args:
        _user_id: User ID (injected automatically)
        feed: RSS feed URL or saved feed name (partial match works)
        max_items: Max articles to return
    """
    url = await _resolve_feed_url(_user_id, feed)
    parsed = await _fetch_and_parse(url)
    articles = []
    for entry in parsed.entries[:max_items]:
        articles.append(
            {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", "")[:300],
                "published": entry.get("published", ""),
            }
        )
    return {
        "feed_title": parsed.feed.get("title", url),
        "url": url,
        "articles": articles,
    }


async def _fetch_one_feed(url: str, name: str, max_items: int) -> list[dict]:
    """Fetch a single feed and return its articles, or empty list on failure."""
    try:
        parsed = await _fetch_and_parse(url)
    except Exception:
        return []
    feed_name = name or parsed.feed.get("title", url)
    return [
        {
            "feed": feed_name,
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
        }
        for entry in parsed.entries[:max_items]
    ]


@mcp.tool()
async def fetch_all_feeds(_user_id: int, max_per_feed: int = 3) -> dict:
    """Scan all saved RSS feeds concurrently and return article titles (no full text).
    Use fetch_feed to read full articles for feeds you find interesting.

    Args:
        _user_id: User ID (injected automatically)
        max_per_feed: Max article titles per feed
    """
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT url, name FROM rss_feeds WHERE user_id = ?", (_user_id,)
        )
        feeds = await cursor.fetchall()

    if not feeds:
        return {
            "error": "No feeds saved yet. Ask the user what feeds they want to add, or suggest some."
        }

    results = await asyncio.gather(
        *[
            _fetch_one_feed(feed_row["url"], feed_row["name"], max_per_feed)
            for feed_row in feeds
        ]
    )
    all_articles = [article for feed_articles in results for article in feed_articles]

    return {
        "total_articles": len(all_articles),
        "hint": "These are titles only. Use fetch_feed with the feed name to get full article summaries for interesting feeds.",
        "articles": all_articles,
    }


@mcp.tool()
async def add_feed(_user_id: int, url: str, name: str = "") -> dict:
    """Save an RSS feed URL. Auto-detects the feed name if not provided.

    Args:
        _user_id: User ID (injected automatically)
        url: RSS feed URL
        name: Friendly name (auto-detected if empty)
    """
    if not name:
        try:
            parsed = await _fetch_and_parse(url)
            name = parsed.feed.get("title", "")
        except Exception:
            pass

    async with aiosqlite.connect(config.db_path) as db:
        try:
            await db.execute(
                "INSERT INTO rss_feeds (user_id, url, name) VALUES (?, ?, ?)",
                (_user_id, url, name),
            )
            await db.commit()
            return {"status": "added", "url": url, "name": name}
        except aiosqlite.IntegrityError:
            return {"status": "already_exists", "url": url}


@mcp.tool()
async def list_feeds(_user_id: int) -> dict:
    """List all saved RSS feeds.

    Args:
        _user_id: User ID (injected automatically)
    """
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, url, name, added_at FROM rss_feeds WHERE user_id = ?",
            (_user_id,),
        )
        rows = await cursor.fetchall()
        return {"feeds": [{k: row[k] for k in row.keys()} for row in rows]}


@mcp.tool()
async def remove_feed(_user_id: int, feed: str) -> dict:
    """Unsubscribe from an RSS feed. Accepts a feed name, URL, or partial match.

    Args:
        _user_id: User ID (injected automatically)
        feed: Feed name or URL to remove (partial match works)
    """
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, url, name FROM rss_feeds WHERE user_id = ? AND (LOWER(name) LIKE ? OR LOWER(url) LIKE ?)",
            (_user_id, f"%{feed.lower()}%", f"%{feed.lower()}%"),
        )
        row = await cursor.fetchone()
        if not row:
            return {"error": f"No feed matching '{feed}' found."}

        await db.execute("DELETE FROM rss_feeds WHERE id = ?", (row["id"],))
        await db.commit()
        return {"status": "removed", "name": row["name"], "url": row["url"]}
