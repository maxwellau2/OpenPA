"""Tests for authentication (signup, login, JWT, credentials)."""

import pytest


@pytest.mark.asyncio
async def test_create_user(db):
    """Create a new user."""
    from db.auth import create_user
    user = await create_user("auth_test@openpa.dev", "pass123", "Auth Test")
    assert user["email"] == "auth_test@openpa.dev"
    assert user["id"] is not None


@pytest.mark.asyncio
async def test_create_duplicate_user(db):
    """Creating a duplicate user should raise ValueError."""
    from db.auth import create_user
    try:
        await create_user("dup@openpa.dev", "pass", "Dup")
    except ValueError:
        pass  # May already exist from other test
    with pytest.raises(ValueError, match="already registered"):
        await create_user("dup@openpa.dev", "pass", "Dup")


@pytest.mark.asyncio
async def test_authenticate_user(db):
    """Login with correct credentials."""
    from db.auth import create_user, authenticate_user
    try:
        await create_user("login@openpa.dev", "secret", "Login")
    except ValueError:
        pass
    user = await authenticate_user("login@openpa.dev", "secret")
    assert user["email"] == "login@openpa.dev"


@pytest.mark.asyncio
async def test_authenticate_wrong_password(db):
    """Login with wrong password should fail."""
    from db.auth import create_user, authenticate_user
    try:
        await create_user("wrongpw@openpa.dev", "correct", "WrongPW")
    except ValueError:
        pass
    with pytest.raises(ValueError, match="Invalid"):
        await authenticate_user("wrongpw@openpa.dev", "wrong")


@pytest.mark.asyncio
async def test_jwt_roundtrip(db):
    """Create a JWT and decode it."""
    from db.auth import create_token, decode_token
    token = create_token(1, "test@openpa.dev")
    payload = decode_token(token)
    assert payload["user_id"] == 1
    assert payload["email"] == "test@openpa.dev"


@pytest.mark.asyncio
async def test_store_and_retrieve_credentials(db):
    """Store and retrieve user credentials."""
    from db.auth import create_user, set_user_credentials, get_user_credentials
    try:
        user = await create_user("creds@openpa.dev", "pass", "Creds")
    except ValueError:
        from db.auth import authenticate_user
        user = await authenticate_user("creds@openpa.dev", "pass")

    await set_user_credentials(user["id"], "github", {"token": "ghp_test123"})
    creds = await get_user_credentials(user["id"], "github")
    assert creds["token"] == "ghp_test123"


@pytest.mark.asyncio
async def test_get_missing_credentials(db):
    """Getting credentials for unconfigured service returns None."""
    from db.auth import create_user, get_user_credentials
    try:
        user = await create_user("nocreds@openpa.dev", "pass", "NoCreds")
    except ValueError:
        from db.auth import authenticate_user
        user = await authenticate_user("nocreds@openpa.dev", "pass")

    creds = await get_user_credentials(user["id"], "nonexistent_service")
    assert creds is None
