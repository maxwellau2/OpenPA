"""Tests for tools that require credentials — verify they fail gracefully without them."""

import pytest
from fastmcp.exceptions import ToolError


@pytest.mark.asyncio
async def test_github_list_repos_no_creds(mcp_client, user):
    """GitHub tools should raise ToolError without credentials."""
    with pytest.raises(ToolError, match="No github credentials"):
        await mcp_client.call_tool("github_list_repos", {"_user_id": user})


@pytest.mark.asyncio
async def test_gmail_get_unread_no_creds(mcp_client, user):
    """Gmail tools should raise ToolError without credentials."""
    with pytest.raises(ToolError, match="No google credentials"):
        await mcp_client.call_tool("gmail_get_unread", {"_user_id": user})


@pytest.mark.asyncio
async def test_calendar_list_events_no_creds(mcp_client, user):
    """Calendar tools should raise ToolError without credentials."""
    with pytest.raises(ToolError, match="No google credentials"):
        await mcp_client.call_tool("calendar_list_events", {"_user_id": user})


@pytest.mark.asyncio
async def test_spotify_play_no_creds(mcp_client, user):
    """Spotify tools should raise ToolError without credentials."""
    with pytest.raises(ToolError, match="No spotify credentials"):
        await mcp_client.call_tool("spotify_play", {"_user_id": user, "query": "test"})


@pytest.mark.asyncio
async def test_discord_list_servers_no_creds(mcp_client, user):
    """Discord tools should raise ToolError without credentials."""
    with pytest.raises(ToolError, match="No discord credentials"):
        await mcp_client.call_tool("discord_list_servers", {"_user_id": user})
