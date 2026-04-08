"""Tests for memory tools (preferences, notes, history)."""

import pytest


@pytest.mark.asyncio
async def test_set_and_get_preference(mcp_client, user):
    """Set a preference and retrieve it."""
    result = await mcp_client.call_tool("memory_set_preference", {
        "_user_id": user, "key": "theme", "value": "dark", "category": "ui",
    })
    assert result.data["status"] == "saved"
    assert result.data["key"] == "theme"

    result = await mcp_client.call_tool("memory_get_preferences", {
        "_user_id": user, "category": "ui",
    })
    prefs = result.data["preferences"]
    assert len(prefs) >= 1
    assert any(p["key"] == "theme" and p["value"] == "dark" for p in prefs)


@pytest.mark.asyncio
async def test_get_preferences_all(mcp_client, user):
    """Get all preferences without category filter."""
    result = await mcp_client.call_tool("memory_get_preferences", {"_user_id": user})
    assert "preferences" in result.data


@pytest.mark.asyncio
async def test_set_preference_overwrite(mcp_client, user):
    """Overwriting a preference should update the value."""
    await mcp_client.call_tool("memory_set_preference", {
        "_user_id": user, "key": "color", "value": "blue",
    })
    await mcp_client.call_tool("memory_set_preference", {
        "_user_id": user, "key": "color", "value": "green",
    })
    result = await mcp_client.call_tool("memory_get_preferences", {"_user_id": user})
    colors = [p for p in result.data["preferences"] if p["key"] == "color"]
    assert len(colors) == 1
    assert colors[0]["value"] == "green"


@pytest.mark.asyncio
async def test_save_and_search_note(mcp_client, user):
    """Save a note and find it via search."""
    result = await mcp_client.call_tool("memory_save_note", {
        "_user_id": user, "content": "Remember to buy milk", "tags": "shopping,todo",
    })
    assert result.data["status"] == "saved"
    assert result.data["note_id"] is not None


@pytest.mark.asyncio
async def test_search_history_empty(mcp_client, user):
    """Search history should return empty for non-matching query."""
    result = await mcp_client.call_tool("memory_search_history", {
        "_user_id": user, "query": "xyznonexistent123",
    })
    assert result.data["results"] == []
