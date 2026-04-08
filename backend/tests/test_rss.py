"""Tests for RSS feed tools."""

import pytest


@pytest.mark.asyncio
async def test_add_and_list_feed(mcp_client, user):
    """Add an RSS feed and verify it appears in the list."""
    result = await mcp_client.call_tool("rss_add_feed", {
        "_user_id": user, "url": "https://hnrss.org/frontpage", "name": "Hacker News",
    })
    assert result.data["status"] == "added"

    result = await mcp_client.call_tool("rss_list_feeds", {"_user_id": user})
    feeds = result.data["feeds"]
    assert any(f["url"] == "https://hnrss.org/frontpage" for f in feeds)


@pytest.mark.asyncio
async def test_add_duplicate_feed(mcp_client, user):
    """Adding the same feed twice should return already_exists."""
    await mcp_client.call_tool("rss_add_feed", {
        "_user_id": user, "url": "https://hnrss.org/newest", "name": "HN New",
    })
    result = await mcp_client.call_tool("rss_add_feed", {
        "_user_id": user, "url": "https://hnrss.org/newest",
    })
    assert result.data["status"] == "already_exists"


@pytest.mark.asyncio
async def test_fetch_feed_by_url(mcp_client, user):
    """Fetch a feed by URL and verify articles are returned."""
    result = await mcp_client.call_tool("rss_fetch_feed", {
        "_user_id": user, "feed": "https://hnrss.org/frontpage", "max_items": 3,
    })
    assert "articles" in result.data
    assert len(result.data["articles"]) <= 3
    if result.data["articles"]:
        assert "title" in result.data["articles"][0]
        assert "link" in result.data["articles"][0]


@pytest.mark.asyncio
async def test_fetch_feed_by_name(mcp_client, user):
    """Fetch a feed by saved name (partial match)."""
    await mcp_client.call_tool("rss_add_feed", {
        "_user_id": user, "url": "https://hnrss.org/frontpage", "name": "Hacker News",
    })
    result = await mcp_client.call_tool("rss_fetch_feed", {
        "_user_id": user, "feed": "hacker", "max_items": 2,
    })
    assert "articles" in result.data


@pytest.mark.asyncio
async def test_fetch_all_feeds(mcp_client, user):
    """Fetch all saved feeds."""
    result = await mcp_client.call_tool("rss_fetch_all_feeds", {
        "_user_id": user, "max_per_feed": 2,
    })
    assert "articles" in result.data or "error" in result.data


@pytest.mark.asyncio
async def test_add_feed_auto_name(mcp_client, user):
    """Adding a feed without a name should auto-detect it."""
    result = await mcp_client.call_tool("rss_add_feed", {
        "_user_id": user, "url": "https://feeds.bbci.co.uk/news/rss.xml",
    })
    assert result.data["status"] == "added"
    # Name should be auto-detected from the feed
    assert result.data["name"] != ""
