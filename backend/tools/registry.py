"""MCP server composition — mounts all tool servers into one."""

from fastmcp import FastMCP

from tools.memory import mcp as memory_mcp
from tools.rss import mcp as rss_mcp
from tools.github import mcp as github_mcp
from tools.gmail import mcp as gmail_mcp
from tools.calendar import mcp as calendar_mcp
from tools.spotify import mcp as spotify_mcp
from tools.discord_tool import mcp as discord_mcp
from tools.telegram import mcp as telegram_mcp
from tools.web_search import mcp as web_search_mcp
from tools.mastodon import mcp as mastodon_mcp
from tools.youtube import mcp as youtube_mcp # Added YouTube tool

# Main MCP server that composes all sub-servers
mcp = FastMCP("openpa")

mcp.mount(memory_mcp, namespace="memory")
mcp.mount(rss_mcp, namespace="rss")
mcp.mount(github_mcp, namespace="github")
mcp.mount(gmail_mcp, namespace="gmail")
mcp.mount(calendar_mcp, namespace="calendar")
mcp.mount(spotify_mcp, namespace="spotify")
mcp.mount(discord_mcp, namespace="discord")
mcp.mount(telegram_mcp, namespace="telegram")
mcp.mount(web_search_mcp, namespace="web")
mcp.mount(mastodon_mcp, namespace="mastodon")
mcp.mount(youtube_mcp, namespace="youtube") # Mounted YouTube tool
