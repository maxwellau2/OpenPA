"""Gmail tools — self-resolving. reply_email can find emails by subject/sender, not just ID."""

import base64
import json
from email.mime.text import MIMEText

import httpx
from fastmcp import FastMCP

from tools.credentials import get_creds

mcp = FastMCP("gmail")
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


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


async def _find_email(token: str, search: str) -> dict | None:
    """Find an email by searching Gmail (subject, sender, etc.)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/messages",
            headers=_auth_headers(token),
            params={"q": search, "maxResults": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("messages"):
            return None

        msg_resp = await client.get(
            f"{API_BASE}/messages/{data['messages'][0]['id']}",
            headers=_auth_headers(token),
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date", "Message-ID"]},
        )
        msg_resp.raise_for_status()
        msg = msg_resp.json()

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "from": headers.get("From", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "message_id": headers.get("Message-ID", ""),
    }


@mcp.tool()
async def get_unread(_user_id: int, max_results: int = 10, query: str = "") -> dict:
    """Fetch unread emails from Gmail.

    Args:
        _user_id: User ID (injected automatically)
        max_results: Maximum number of emails to return
        query: Gmail search query (e.g. 'from:boss@company.com')
    """
    token = await _get_token(_user_id)
    q = "is:unread"
    if query:
        q += f" {query}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/messages",
            headers=_auth_headers(token),
            params={"q": q, "maxResults": max_results},
        )
        resp.raise_for_status()
        data = resp.json()

    if not data.get("messages"):
        return {"emails": [], "count": 0}

    emails = []
    async with httpx.AsyncClient() as client:
        for msg_ref in data["messages"][:max_results]:
            msg_resp = await client.get(
                f"{API_BASE}/messages/{msg_ref['id']}",
                headers=_auth_headers(token),
                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            msg_resp.raise_for_status()
            msg = msg_resp.json()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            emails.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "snippet": msg.get("snippet", ""),
                "date": headers.get("Date", ""),
            })

    return {"emails": emails, "count": len(emails)}


@mcp.tool()
async def read_email(_user_id: int, email_id: str = "", search: str = "") -> dict:
    """Read the full content of an email. Can find by ID or by searching (subject, sender name, etc.).

    Args:
        _user_id: User ID (injected automatically)
        email_id: The email message ID (if you have it)
        search: Search query to find the email (e.g. 'from:john subject:meeting')
    """
    token = await _get_token(_user_id)

    if not email_id and search:
        found = await _find_email(token, search)
        if not found:
            return {"error": f"No email found matching '{search}'"}
        email_id = found["id"]

    if not email_id:
        return {"error": "Provide either email_id or search query."}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/messages/{email_id}",
            headers=_auth_headers(token),
            params={"format": "full"},
        )
        resp.raise_for_status()
        msg = resp.json()

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

    body = ""
    payload = msg.get("payload", {})
    if payload.get("body", {}).get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    elif payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break

    return {
        "id": email_id,
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "body": body[:5000],
    }


@mcp.tool()
async def send_email(_user_id: int, to: str, subject: str, body: str) -> dict:
    """Send a new email.

    Args:
        _user_id: User ID (injected automatically)
        to: Recipient email address
        subject: Email subject
        body: Email body text
    """
    token = await _get_token(_user_id)

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/messages/send",
            headers=_auth_headers(token),
            json={"raw": raw},
        )
        resp.raise_for_status()
        result = resp.json()

    return {"status": "sent", "message_id": result["id"]}


@mcp.tool()
async def reply_email(_user_id: int, email_id: str = "", search: str = "", body: str = "") -> dict:
    """Reply to an email. Can find the email by ID or by searching (subject, sender, etc.).

    Args:
        _user_id: User ID (injected automatically)
        email_id: The email message ID (if you have it)
        search: Search query to find the email to reply to (e.g. 'from:john subject:meeting')
        body: Reply body text
    """
    token = await _get_token(_user_id)

    # Resolve email
    if not email_id and search:
        found = await _find_email(token, search)
        if not found:
            return {"error": f"No email found matching '{search}'"}
        email_id = found["id"]

    if not email_id:
        return {"error": "Provide either email_id or search query."}

    # Get original message headers
    async with httpx.AsyncClient() as client:
        orig_resp = await client.get(
            f"{API_BASE}/messages/{email_id}",
            headers=_auth_headers(token),
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Message-ID"]},
        )
        orig_resp.raise_for_status()
        orig = orig_resp.json()

    headers = {h["name"]: h["value"] for h in orig.get("payload", {}).get("headers", [])}
    thread_id = orig.get("threadId", "")

    message = MIMEText(body)
    message["to"] = headers.get("From", "")
    message["subject"] = f"Re: {headers.get('Subject', '')}"
    message["In-Reply-To"] = headers.get("Message-ID", "")
    message["References"] = headers.get("Message-ID", "")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/messages/send",
            headers=_auth_headers(token),
            json={"raw": raw, "threadId": thread_id},
        )
        resp.raise_for_status()
        result = resp.json()

    return {"status": "sent", "message_id": result["id"], "replied_to": headers.get("From", "")}
