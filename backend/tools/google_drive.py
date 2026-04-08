"""Google Drive tools for managing files."""

import base64
import json
import io

import httpx
from fastmcp import FastMCP

from tools.credentials import get_creds

mcp = FastMCP("google_drive")
API_BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_API_BASE = "https://www.googleapis.com/upload/drive/v3"


async def _get_token(user_id: int) -> str:
    """Get a valid OAuth2 access token, refreshing if needed."""
    creds = await get_creds(user_id, "google")

    if creds.get("expiry") and creds.get("refresh_token"):
        from datetime import datetime, timezone
        try:
            expiry = datetime.fromisoformat(creds["expiry"].replace("Z", "+00:00"))
            if expiry < datetime.now(timezone.utc):
                creds = await _refresh_token(user_id, creds)
        except (ValueError, KeyError):
            pass

    return creds["token"]


async def _refresh_token(user_id: int, creds: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        new_data = resp.json()

    creds["token"] = new_data["access_token"]
    if "expires_in" in new_data:
        from datetime import datetime, timedelta, timezone
        expiry = datetime.now(timezone.utc) + timedelta(seconds=new_data["expires_in"])
        creds["expiry"] = expiry.isoformat()

    from db.auth import set_user_credentials
    await set_user_credentials(user_id, "google", creds)
    return creds


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@mcp.tool()
async def list_files(_user_id: int, query: str = "", max_results: int = 10) -> dict:
    """List files in Google Drive.

    Args:
        _user_id: User ID (injected automatically)
        query: Search query for files (e.g., "name contains 'report' and mimeType = 'application/pdf'")
        max_results: Maximum number of files to return
    """
    token = await _get_token(_user_id)
    params = {"pageSize": max_results, "fields": "files(id, name, mimeType, modifiedTime)"}
    if query:
        params["q"] = query

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/files",
            headers=_auth_headers(token),
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

    return {"files": data.get("files", [])}


@mcp.tool()
async def upload_file(_user_id: int, name: str, content: str, mime_type: str = "text/plain", parents: list = None) -> dict:
    """Upload a file to Google Drive.

    Args:
        _user_id: User ID (injected automatically)
        name: Name of the file
        content: Content of the file (as a string)
        mime_type: MIME type of the file (e.g., "text/plain", "application/pdf")
        parents: List of parent folder IDs (optional)
    """
    token = await _get_token(_user_id)

    metadata = {"name": name, "mimeType": mime_type}
    if parents:
        metadata["parents"] = parents

    headers = _auth_headers(token)
    headers["Content-Type"] = "application/json; charset=UTF-8"

    async with httpx.AsyncClient() as client:
        # Create file metadata
        resp = await client.post(
            f"{UPLOAD_API_BASE}/files?uploadType=resumable",
            headers=headers,
            json=metadata,
        )
        resp.raise_for_status()
        location_url = resp.headers["Location"]

        # Upload file content
        upload_headers = _auth_headers(token)
        upload_headers["Content-Type"] = mime_type
        
        resp = await client.put(
            location_url,
            headers=upload_headers,
            content=content.encode("utf-8"),
        )
        resp.raise_for_status()
        result = resp.json()

    return {"status": "uploaded", "file_id": result["id"], "name": result["name"]}


@mcp.tool()
async def download_file(_user_id: int, file_id: str) -> dict:
    """Download a file from Google Drive.

    Args:
        _user_id: User ID (injected automatically)
        file_id: The ID of the file to download
    """
    token = await _get_token(_user_id)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/files/{file_id}?alt=media",
            headers=_auth_headers(token),
        )
        resp.raise_for_status()

    return {"file_content": resp.text}
