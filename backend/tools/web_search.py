"""Web search tool using DuckDuckGo. No API key needed."""

from ddgs import DDGS
from fastmcp import FastMCP

mcp = FastMCP("web_search")


@mcp.tool()
async def search(_user_id: int, query: str, num_results: int = 10) -> dict:
    """Search the web for anything. No API key needed. Use this for current information, facts, news, prices, or anything you don't know.

    Args:
        _user_id: User ID (injected automatically)
        query: Search query (e.g. "latest bitcoin price", "weather in singapore")
        num_results: Number of results to return (max 30)
    """
    num_results = min(num_results, 30)

    try:
        results = DDGS().text(query, max_results=num_results)
    except Exception as e:
        return {"query": query, "count": 0, "results": [], "error": str(e)}

    formatted = [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": r.get("body", "")[:300],
        }
        for r in results
    ]

    return {"query": query, "count": len(formatted), "results": formatted}
