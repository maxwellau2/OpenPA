"""Google Calendar tools. Uses same Google OAuth creds as Gmail."""

from datetime import datetime, timedelta, timezone

import httpx
from fastmcp import FastMCP


mcp = FastMCP("calendar")
API_BASE = "https://www.googleapis.com/calendar/v3"


async def _get_token(user_id: int) -> str:
    """Reuse Gmail's OAuth token refresh logic."""
    from tools.gmail import _get_token as gmail_get_token

    return await gmail_get_token(user_id)


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _parse_date(value: str, now: datetime) -> datetime:
    """Parse a date string, handling natural language like 'today', 'tomorrow', 'yesterday'."""
    v = value.strip().lower()
    if v in ("today", "now"):
        return now
    if v == "tomorrow":
        return now + timedelta(days=1)
    if v == "yesterday":
        return now - timedelta(days=1)
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return now


@mcp.tool()
async def list_events(
    _user_id: int, date_from: str = "", date_to: str = "", max_results: int = 20
) -> dict:
    """List upcoming calendar events.

    Args:
        _user_id: User ID (injected automatically)
        date_from: Start date (ISO format, e.g. 2025-04-07). Defaults to today.
        date_to: End date (ISO format). Defaults to 7 days from now.
        max_results: Maximum events to return
    """
    token = await _get_token(_user_id)

    now = datetime.now(timezone.utc)
    time_min = _parse_date(date_from, now) if date_from else now
    time_max = _parse_date(date_to, now) if date_to else time_min + timedelta(days=7)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/calendars/primary/events",
            headers=_auth_headers(token),
            params={
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "maxResults": max_results,
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    events = []
    for event in data.get("items", []):
        start = event.get("start", {})
        end = event.get("end", {})
        events.append(
            {
                "id": event["id"],
                "title": event.get("summary", "(No title)"),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "location": event.get("location", ""),
                "description": (event.get("description", "") or "")[:200],
            }
        )

    return {"events": events, "count": len(events)}


@mcp.tool()
async def create_event(
    _user_id: int,
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
) -> dict:
    """Create a new calendar event.

    Args:
        _user_id: User ID (injected automatically)
        title: Event title
        start: Start datetime (ISO format, e.g. 2025-04-07T10:00:00)
        end: End datetime (ISO format)
        description: Event description
        location: Event location
    """
    token = await _get_token(_user_id)

    event_body = {
        "summary": title,
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
    }
    if description:
        event_body["description"] = description
    if location:
        event_body["location"] = location

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/calendars/primary/events",
            headers=_auth_headers(token),
            json=event_body,
        )
        resp.raise_for_status()
        event = resp.json()

    return {"id": event["id"], "url": event.get("htmlLink", ""), "status": "created"}


@mcp.tool()
async def delete_event(_user_id: int, event_id: str) -> dict:
    """Delete a calendar event.

    Args:
        _user_id: User ID (injected automatically)
        event_id: The event ID to delete
    """
    token = await _get_token(_user_id)

    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{API_BASE}/calendars/primary/events/{event_id}",
            headers=_auth_headers(token),
        )
        resp.raise_for_status()

    return {"status": "deleted", "event_id": event_id}
