"""Helper to fetch per-user credentials from the DB."""

from db.auth import get_user_credentials


async def get_creds(user_id: int, service: str) -> dict:
    """Get a user's credentials for a service. Raises if not configured."""
    creds = await get_user_credentials(user_id, service)
    if not creds:
        raise RuntimeError(
            f"No {service} credentials configured. "
            f"Use PUT /api/config/{service} to add your API keys."
        )
    return creds
