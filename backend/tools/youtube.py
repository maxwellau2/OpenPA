"""YouTube tools — download videos."""

import yt_dlp
import os
import asyncio
import uuid
import aiofiles
from fastmcp import FastMCP

mcp = FastMCP("youtube")

# Store downloaded video information temporarily
# In a real-world scenario, this would be a more robust temporary storage
# with proper cleanup mechanisms (e.g., a dedicated cleanup service,
# or a database entry with an expiry and a cron job).
# For this example, we'll just keep track of the file path.
DOWNLOADED_VIDEOS = {}

@mcp.tool()
async def download_video(_user_id: int, url: str) -> dict:
    """Download a YouTube video by URL.

    Args:
        _user_id: User ID (injected automatically)
        url: The URL of the YouTube video to download.
    """
    video_id = str(uuid.uuid4())
    temp_dir = "/tmp/youtube_downloads"
    os.makedirs(temp_dir, exist_ok=True)
    filepath = os.path.join(temp_dir, f"{video_id}.mp4")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': filepath,
        'noplaylist': True,
        'progress_hooks': [lambda d: print(d['status'])], # For debugging download status
    }

    try:
        # yt-dlp is not async, so run it in a thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))

        if os.path.exists(filepath):
            DOWNLOADED_VIDEOS[video_id] = filepath
            # Schedule deletion after 20 minutes (1200 seconds)
            # This is a basic in-memory timer. For production, consider a persistent queue/scheduler.
            async def delete_file_after_delay(path, delay):
                await asyncio.sleep(delay)
                if os.path.exists(path):
                    os.remove(path)
                    print(f"Deleted temporary file: {path}")
                    DOWNLOADED_VIDEOS.pop(video_id, None)

            asyncio.create_task(delete_file_after_delay(filepath, 1200)) # 20 minutes

            return {"status": "success", "message": f"Video downloaded to {filepath}. It will be deleted in 20 minutes.", "video_id": video_id}
        else:
            return {"status": "error", "message": "Video download failed: File not found after download attempt."}
    except Exception as e:
        return {"status": "error", "message": f"Video download failed: {str(e)}"}
