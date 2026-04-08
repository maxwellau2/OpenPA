"""YouTube tools — download videos via yt-dlp, serve via a temp download endpoint."""

import asyncio
import os
import time
import uuid
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("youtube")

DOWNLOAD_DIR = Path("/tmp/openpa_youtube")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Track downloads: {download_id: {path, filename, created_at, user_id}}
_downloads: dict[str, dict] = {}

# Auto-cleanup after 20 minutes
EXPIRY_SECONDS = 1200


def _cleanup_expired():
    """Remove expired downloads."""
    now = time.time()
    expired = [k for k, v in _downloads.items() if now - v["created_at"] > EXPIRY_SECONDS]
    for k in expired:
        path = _downloads[k]["path"]
        if os.path.exists(path):
            os.remove(path)
        del _downloads[k]


def get_download_info(download_id: str) -> dict | None:
    """Get download info by ID — used by the REST API download endpoint."""
    _cleanup_expired()
    return _downloads.get(download_id)


@mcp.tool()
async def download_video(_user_id: int, url: str) -> dict:
    """Download a YouTube video by URL. Returns a download link that expires in 20 minutes.

    Args:
        _user_id: User ID (injected automatically)
        url: The YouTube video URL
    """
    import yt_dlp

    _cleanup_expired()

    download_id = str(uuid.uuid4())[:8]
    output_template = str(DOWNLOAD_DIR / f"{download_id}_%(title)s.%(ext)s")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    info = {"title": "video"}
    try:
        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _download)
        info["title"] = result.get("title", "video")
    except Exception as e:
        return {"status": "error", "message": f"Download failed: {e}"}

    # Find the downloaded file
    downloaded = list(DOWNLOAD_DIR.glob(f"{download_id}_*"))
    if not downloaded:
        return {"status": "error", "message": "Download completed but file not found"}

    filepath = downloaded[0]
    _downloads[download_id] = {
        "path": str(filepath),
        "filename": filepath.name,
        "created_at": time.time(),
        "user_id": _user_id,
        "title": info["title"],
    }

    return {
        "status": "success",
        "title": info["title"],
        "download_id": download_id,
        "download_url": f"/api/download/{download_id}",
        "filename": filepath.name,
        "expires_in": "20 minutes",
    }


@mcp.tool()
async def get_video_info(_user_id: int, url: str) -> dict:
    """Get information about a YouTube video without downloading it.

    Args:
        _user_id: User ID (injected automatically)
        url: The YouTube video URL
    """
    import yt_dlp

    ydl_opts = {"quiet": True, "no_warnings": True}

    try:
        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _extract)
    except Exception as e:
        return {"status": "error", "message": f"Failed to get info: {e}"}

    return {
        "title": info.get("title", ""),
        "duration": info.get("duration", 0),
        "uploader": info.get("uploader", ""),
        "view_count": info.get("view_count", 0),
        "description": (info.get("description", "") or "")[:500],
        "thumbnail": info.get("thumbnail", ""),
    }
