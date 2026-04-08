"""RSS feed tools — self-resolving. fetch_feed can accept a name or URL."""

import aiosqlite
import feedparser
from fastmcp import FastMCP

from config import config

mcp = FastMCP("rss")


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
    parsed = feedparser.parse(url)
    articles = []
    for entry in parsed.entries[:max_items]:
        articles.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "summary": entry.get("summary", "")[:300],
            "published": entry.get("published", ""),
        })
    return {"feed_title": parsed.feed.get("title", url), "url": url, "articles": articles}


@mcp.tool()
async def fetch_all_feeds(_user_id: int, max_per_feed: int = 5) -> dict:
    """Fetch all saved RSS feeds and return articles from each.

    Args:
        _user_id: User ID (injected automatically)
        max_per_feed: Max articles per feed
    """
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT url, name FROM rss_feeds WHERE user_id = ?", (_user_id,)
        )
        feeds = await cursor.fetchall()

    if not feeds:
        return {"error": "No feeds saved yet. Ask the user what feeds they want to add, or suggest some."}

    all_articles = []
    for feed_row in feeds:
        parsed = feedparser.parse(feed_row["url"])
        for entry in parsed.entries[:max_per_feed]:
            all_articles.append({
                "feed": feed_row["name"] or parsed.feed.get("title", ""),
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", "")[:300],
                "published": entry.get("published", ""),
            })
    return {"total_articles": len(all_articles), "articles": all_articles}


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
            parsed = feedparser.parse(url)
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
            "SELECT id, url, name, added_at FROM rss_feeds WHERE user_id = ?", (_user_id,)
        )
        rows = await cursor.fetchall()
        return {"feeds": [{k: row[k] for k in row.keys()} for row in rows]}
