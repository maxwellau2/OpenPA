"""Web scraping tool — fetch and extract structured content from web pages."""

import re

import httpx
from fastmcp import FastMCP

mcp = FastMCP("web_scrape")

MAX_CONTENT_CHARS = 50000


def _strip_html(html: str) -> str:
    """Strip HTML tags, scripts, styles, and normalize whitespace."""
    # Remove script and style blocks
    text = re.sub(
        r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Convert common block elements to newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|div|tr|li|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</t[dh]>", "\t", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&nbsp;", " ").replace("&#39;", "'")
    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _extract_tables(html: str) -> list[list[list[str]]]:
    """Extract HTML tables as lists of rows, each row a list of cell texts."""
    tables = []
    for table_match in re.finditer(
        r"<table[^>]*>(.*?)</table>", html, flags=re.DOTALL | re.IGNORECASE
    ):
        table_html = table_match.group(1)
        rows = []
        for row_match in re.finditer(
            r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL | re.IGNORECASE
        ):
            cells = []
            for cell_match in re.finditer(
                r"<t[dh][^>]*>(.*?)</t[dh]>",
                row_match.group(1),
                flags=re.DOTALL | re.IGNORECASE,
            ):
                cell_text = re.sub(r"<[^>]+>", "", cell_match.group(1)).strip()
                cells.append(cell_text)
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def _extract_links(html: str, base_url: str = "") -> list[dict]:
    """Extract links from HTML."""
    links = []
    for match in re.finditer(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        href, text = match.group(1), re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if text and href and not href.startswith(("#", "javascript:")):
            links.append({"url": href, "text": text[:200]})
    return links[:100]  # Cap at 100 links


async def _fetch_html(url: str) -> str:
    """Fetch a URL and return HTML. Raises a readable error on failure."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url, headers={"User-Agent": "OpenPA/1.0"})
            resp.raise_for_status()
            return resp.text
    except httpx.ConnectError:
        raise RuntimeError(f"Could not connect to {url} — check the URL is correct")
    except httpx.TimeoutException:
        raise RuntimeError(f"Request to {url} timed out")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"HTTP {e.response.status_code} fetching {url}")


@mcp.tool()
async def fetch_page(_user_id: int, url: str) -> dict:
    """Fetch a web page and return its text content (HTML stripped). Good for reading articles, docs, wiki pages.

    Args:
        _user_id: User ID (injected automatically)
        url: URL of the page to fetch
    """
    html = await _fetch_html(url)

    text = _strip_html(html)
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
    )
    title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""

    return {
        "url": url,
        "title": title,
        "content": text[:MAX_CONTENT_CHARS],
        "length": len(text),
    }


@mcp.tool()
async def fetch_tables(_user_id: int, url: str) -> dict:
    """Fetch a web page and extract all HTML tables as structured data. Perfect for Wikipedia tables, stats pages, leaderboards, etc.

    Args:
        _user_id: User ID (injected automatically)
        url: URL of the page to fetch tables from
    """
    html = await _fetch_html(url)

    tables = _extract_tables(html)
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
    )
    title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""

    # Format tables for readability
    formatted = []
    for i, table in enumerate(tables):
        if len(table) < 2:  # Skip trivial tables
            continue
        formatted.append(
            {
                "table_index": i,
                "header": table[0] if table else [],
                "rows": table[1:50],  # Cap at 50 rows
                "total_rows": len(table) - 1,
            }
        )

    return {
        "url": url,
        "title": title,
        "tables_found": len(formatted),
        "tables": formatted[:10],  # Cap at 10 tables
    }


@mcp.tool()
async def fetch_links(_user_id: int, url: str) -> dict:
    """Fetch a web page and extract all links. Useful for discovering related pages or navigating a site.

    Args:
        _user_id: User ID (injected automatically)
        url: URL of the page to extract links from
    """
    html = await _fetch_html(url)

    links = _extract_links(html, url)

    return {
        "url": url,
        "links_found": len(links),
        "links": links,
    }
