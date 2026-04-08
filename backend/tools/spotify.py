"""Spotify tools — self-resolving with auto-token-refresh and error handling."""

import base64

import httpx
from fastmcp import FastMCP

from tools.credentials import get_creds

mcp = FastMCP("spotify")
API_BASE = "https://api.spotify.com/v1"


async def _get_headers(user_id: int) -> dict:
    """Get auth headers, refreshing the token if expired."""
    creds = await get_creds(user_id, "spotify")

    # Try a simple API call to see if token is valid
    headers = {"Authorization": f"Bearer {creds['access_token']}"}
    async with httpx.AsyncClient() as client:
        test = await client.get(f"{API_BASE}/me", headers=headers)
        if test.status_code == 401 and creds.get("refresh_token"):
            # Token expired — refresh it
            auth = base64.b64encode(
                f"{creds['client_id']}:{creds['client_secret']}".encode()
            ).decode()
            resp = await client.post(
                "https://accounts.spotify.com/api/token",
                headers={"Authorization": f"Basic {auth}"},
                data={"grant_type": "refresh_token", "refresh_token": creds["refresh_token"]},
            )
            if resp.is_success:
                new_data = resp.json()
                creds["access_token"] = new_data["access_token"]
                from db.auth import set_user_credentials
                await set_user_credentials(user_id, "spotify", creds)
                headers = {"Authorization": f"Bearer {creds['access_token']}"}

    return headers


@mcp.tool()
async def play(_user_id: int, query: str = "", uri: str = "") -> dict:
    """Play music on Spotify. Just describe what you want to hear — it auto-searches.
    Examples: "lo-fi hip hop", "focus music", "Beatles", "chill playlist".
    Leave empty to resume playback. NOTE: Spotify must be open on a device.

    Args:
        _user_id: User ID (injected automatically)
        query: What to play (artist, song, genre, mood) — auto-searches Spotify
        uri: Spotify URI if you already have one (optional)
    """
    headers = await _get_headers(_user_id)

    # If query given but no URI, search for it
    if query and not uri:
        mood_words = {"focus", "chill", "relax", "study", "workout", "party", "sleep",
                      "lo-fi", "lofi", "ambient", "jazz", "classical", "calm", "energy"}

        # Try playlist first for mood/genre queries
        if any(w in query.lower() for w in mood_words):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{API_BASE}/search", headers=headers,
                    params={"q": query, "type": "playlist", "limit": 1},
                )
                if resp.is_success:
                    items = resp.json().get("playlists", {}).get("items", [])
                    items = [i for i in items if i is not None]
                    if items:
                        uri = items[0]["uri"]

        # If no playlist found, search for a track
        if not uri:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{API_BASE}/search", headers=headers,
                    params={"q": query, "type": "track", "limit": 1},
                )
                if resp.is_success:
                    items = resp.json().get("tracks", {}).get("items", [])
                    items = [i for i in items if i is not None]
                    if items:
                        uri = items[0]["uri"]

        if not uri:
            return {"error": f"No results found for '{query}'"}

    # Build request body
    body = {}
    if uri:
        if ":playlist:" in uri or ":album:" in uri:
            body["context_uri"] = uri
        else:
            body["uris"] = [uri]

    async with httpx.AsyncClient() as client:
        # Check for active device; if none, transfer playback to the first available one
        devices_resp = await client.get(f"{API_BASE}/me/player/devices", headers=headers)
        if devices_resp.is_success:
            devices = devices_resp.json().get("devices", [])
            active = [d for d in devices if d.get("is_active")]
            if not active and devices:
                # Transfer playback to first available device
                device_id = devices[0]["id"]
                await client.put(
                    f"{API_BASE}/me/player",
                    headers=headers,
                    json={"device_ids": [device_id], "play": False},
                )
                # Give Spotify a moment to activate
                import asyncio
                await asyncio.sleep(1)
            elif not devices:
                return {"error": "No Spotify devices found. Open Spotify on any device first."}

        resp = await client.put(
            f"{API_BASE}/me/player/play", headers=headers,
            json=body if body else None,
        )
        if resp.status_code in (200, 204):
            return {"status": "playing", "query": query or "resumed"}
        if resp.status_code == 404:
            return {"error": "No active Spotify device found. Open Spotify on your phone or computer and try again."}
        if resp.status_code == 403:
            return {"error": "Spotify playback requires a Premium account."}
        resp.raise_for_status()

    return {"status": "playing"}


@mcp.tool()
async def pause(_user_id: int) -> dict:
    """Pause Spotify playback.

    Args:
        _user_id: User ID (injected automatically)
    """
    headers = await _get_headers(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.put(f"{API_BASE}/me/player/pause", headers=headers)
        if resp.status_code in (200, 204):
            return {"status": "paused"}
        if resp.status_code == 404:
            return {"error": "No active Spotify device found."}
        resp.raise_for_status()
    return {"status": "paused"}


@mcp.tool()
async def current_track(_user_id: int) -> dict:
    """Get the currently playing track on Spotify.

    Args:
        _user_id: User ID (injected automatically)
    """
    headers = await _get_headers(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/me/player/currently-playing", headers=headers)
        if resp.status_code == 204:
            return {"status": "nothing_playing"}
        if resp.status_code == 401:
            return {"error": "Spotify token expired. Please reconnect Spotify in Settings."}
        resp.raise_for_status()
        data = resp.json()

    item = data.get("item", {})
    if not item:
        return {"status": "nothing_playing"}

    return {
        "track": item.get("name", ""),
        "artist": ", ".join(a["name"] for a in item.get("artists", [])),
        "album": item.get("album", {}).get("name", ""),
        "is_playing": data.get("is_playing", False),
    }


@mcp.tool()
async def search(_user_id: int, query: str, type: str = "track", limit: int = 5) -> dict:
    """Search Spotify for tracks, albums, or playlists.

    Args:
        _user_id: User ID (injected automatically)
        query: Search query
        type: Type: track, album, playlist, artist
        limit: Max results
    """
    headers = await _get_headers(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/search", headers=headers,
            params={"q": query, "type": type, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    type_key = f"{type}s"
    for item in data.get(type_key, {}).get("items", []):
        if item is None:
            continue
        result = {"name": item.get("name", ""), "uri": item.get("uri", "")}
        if type == "track" and item.get("artists"):
            result["artist"] = ", ".join(a["name"] for a in item.get("artists", []))
            result["album"] = item.get("album", {}).get("name", "")
        results.append(result)

    return {"results": results}


@mcp.tool()
async def get_playlists(_user_id: int, limit: int = 20) -> dict:
    """Get the user's Spotify playlists.

    Args:
        _user_id: User ID (injected automatically)
        limit: Max playlists to return
    """
    headers = await _get_headers(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/me/playlists", headers=headers, params={"limit": limit})
        resp.raise_for_status()
        data = resp.json()

    return {"playlists": [
        {"name": p["name"], "uri": p["uri"], "tracks": p["tracks"]["total"]}
        for p in data.get("items", [])
        if p is not None
    ]}
