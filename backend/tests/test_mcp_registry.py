"""Tests for the MCP server registry — verify all tools load and have correct schemas."""

import pytest


@pytest.mark.asyncio
async def test_all_tools_loaded(mcp_client):
    """All expected tools should be registered."""
    tools = await mcp_client.list_tools()
    names = [t.name for t in tools]

    expected = [
        # Memory
        "memory_get_preferences",
        "memory_set_preference",
        "memory_search_history",
        "memory_save_note",
        # RSS
        "rss_fetch_feed",
        "rss_fetch_all_feeds",
        "rss_add_feed",
        "rss_list_feeds",
        "rss_remove_feed",
        # GitHub
        "github_list_repos",
        "github_list_prs",
        "github_get_pr_diff",
        "github_create_issue",
        "github_create_pr",
        "github_list_notifications",
        "github_push_file",
        # Gmail
        "gmail_get_unread",
        "gmail_read_email",
        "gmail_send_email",
        "gmail_reply_email",
        # Calendar
        "calendar_list_events",
        "calendar_create_event",
        "calendar_delete_event",
        # Spotify
        "spotify_play",
        "spotify_pause",
        "spotify_current_track",
        "spotify_search",
        "spotify_get_playlists",
        # Discord
        "discord_list_servers",
        "discord_list_channels",
        "discord_send_message",
        "discord_read_messages",
        # Telegram
        "telegram_send_message",
        # Web search
        "web_search",
        # Weather
        "weather_get_current_weather",
        "weather_get_weather_forecast",
    ]

    for tool_name in expected:
        assert tool_name in names, f"Missing tool: {tool_name}"


@pytest.mark.asyncio
async def test_tools_have_descriptions(mcp_client):
    """Every tool should have a non-empty description."""
    tools = await mcp_client.list_tools()
    for t in tools:
        assert t.description, f"Tool {t.name} has no description"


@pytest.mark.asyncio
async def test_tools_have_schemas(mcp_client):
    """Every tool should have an input schema with _user_id."""
    tools = await mcp_client.list_tools()
    for t in tools:
        assert t.inputSchema, f"Tool {t.name} has no input schema"
        props = t.inputSchema.get("properties", {})
        assert "_user_id" in props, f"Tool {t.name} missing _user_id param"


@pytest.mark.asyncio
async def test_tool_count(mcp_client):
    """Verify total tool count."""
    tools = await mcp_client.list_tools()
    assert len(tools) == 88, f"Expected 88 tools, got {len(tools)}"
