"""Tests for web search tool (DuckDuckGo)."""

import pytest


@pytest.mark.asyncio
async def test_search_returns_results(mcp_client, user):
    """Basic search should return results (may be 0 if DDG rate-limits)."""
    result = await mcp_client.call_tool(
        "web_search",
        {
            "_user_id": user,
            "query": "python programming language",
            "num_results": 5,
        },
    )
    assert "count" in result.data
    assert "results" in result.data
    # DDG may rate-limit in CI, so we just check the structure is correct
    assert isinstance(result.data["results"], list)


@pytest.mark.asyncio
async def test_search_result_fields(mcp_client, user):
    """Each result should have title, url, and snippet."""
    result = await mcp_client.call_tool(
        "web_search",
        {
            "_user_id": user,
            "query": "openai",
            "num_results": 3,
        },
    )
    for r in result.data["results"]:
        assert "title" in r
        assert "url" in r
        assert "snippet" in r
        assert r["url"].startswith("http")


@pytest.mark.asyncio
async def test_search_respects_limit(mcp_client, user):
    """Should not return more results than requested."""
    result = await mcp_client.call_tool(
        "web_search",
        {
            "_user_id": user,
            "query": "weather today",
            "num_results": 3,
        },
    )
    assert result.data["count"] <= 3


@pytest.mark.asyncio
async def test_search_max_cap(mcp_client, user):
    """Requesting more than 30 should be capped at 30."""
    result = await mcp_client.call_tool(
        "web_search",
        {
            "_user_id": user,
            "query": "bitcoin",
            "num_results": 100,
        },
    )
    assert result.data["count"] <= 30


@pytest.mark.asyncio
async def test_search_query_preserved(mcp_client, user):
    """The query should be echoed back in the response."""
    result = await mcp_client.call_tool(
        "web_search",
        {
            "_user_id": user,
            "query": "singapore weather",
        },
    )
    assert result.data["query"] == "singapore weather"
