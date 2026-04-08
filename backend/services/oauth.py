"""OAuth flow endpoints for Google, GitHub, Spotify, and Discord."""

import base64
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import RedirectResponse
from loguru import logger

from config import config as cfg
from db.auth import decode_token, get_user, set_user_credentials

router = APIRouter(prefix="/auth", tags=["oauth"])


def _verify_state(state: str) -> dict:
    """Verify JWT from the OAuth state param and return the user."""
    try:
        return decode_token(state)
    except Exception:
        raise HTTPException(401, "Invalid state token")


async def _get_user_from_state(state: str) -> dict:
    payload = _verify_state(state)
    user = await get_user(payload["user_id"])
    if not user:
        raise HTTPException(401, "User not found")
    return user


# ============================================================
# Google OAuth
# ============================================================

@router.get("/google")
async def google_start(token: str = Query(...)):
    """Start Google OAuth. Pass user JWT as ?token="""
    if not cfg.google.client_id:
        raise HTTPException(500, "GOOGLE_CLIENT_ID not configured")
    _verify_state(token)

    params = {
        "client_id": cfg.google.client_id,
        "redirect_uri": cfg.google.redirect_uri,
        "response_type": "code",
        "scope": " ".join(cfg.google.scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": token,
    }
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}")


@router.get("/google/callback")
async def google_callback(code: str = Query(...), state: str = Query("")):
    user = await _get_user_from_state(state)

    async with httpx.AsyncClient() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": cfg.google.client_id,
            "client_secret": cfg.google.client_secret,
            "redirect_uri": cfg.google.redirect_uri,
            "grant_type": "authorization_code",
        })
        if not resp.is_success:
            logger.error(f"Google token exchange failed: {resp.text}")
            raise HTTPException(400, "Failed to exchange code")
        data = resp.json()

    expiry = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
    await set_user_credentials(user["id"], "google", {
        "token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "client_id": cfg.google.client_id,
        "client_secret": cfg.google.client_secret,
        "expiry": expiry.isoformat(),
    })
    logger.info(f"Google OAuth done for {user['email']}")
    return RedirectResponse(f"{cfg.frontend_url}/settings?connected=google")


# ============================================================
# GitHub OAuth
# ============================================================

@router.get("/github")
async def github_start(token: str = Query(...)):
    """Start GitHub OAuth. Pass user JWT as ?token="""
    if not cfg.github.client_id:
        raise HTTPException(500, "GITHUB_CLIENT_ID not configured")
    _verify_state(token)

    params = {
        "client_id": cfg.github.client_id,
        "redirect_uri": cfg.github.redirect_uri,
        "scope": " ".join(cfg.github.scopes),
        "state": token,
    }
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}")


@router.get("/github/callback")
async def github_callback(code: str = Query(...), state: str = Query("")):
    user = await _get_user_from_state(state)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": cfg.github.client_id,
                "client_secret": cfg.github.client_secret,
                "code": code,
                "redirect_uri": cfg.github.redirect_uri,
            },
        )
        if not resp.is_success:
            logger.error(f"GitHub token exchange failed: {resp.text}")
            raise HTTPException(400, "Failed to exchange code")
        data = resp.json()

    if "error" in data:
        raise HTTPException(400, data.get("error_description", data["error"]))

    await set_user_credentials(user["id"], "github", {
        "token": data["access_token"],
        "token_type": data.get("token_type", "bearer"),
        "scope": data.get("scope", ""),
    })
    logger.info(f"GitHub OAuth done for {user['email']}")
    return RedirectResponse(f"{cfg.frontend_url}/settings?connected=github")


# ============================================================
# Spotify OAuth
# ============================================================

@router.get("/spotify")
async def spotify_start(token: str = Query(...)):
    """Start Spotify OAuth. Pass user JWT as ?token="""
    if not cfg.spotify.client_id:
        raise HTTPException(500, "SPOTIFY_CLIENT_ID not configured")
    _verify_state(token)

    params = {
        "client_id": cfg.spotify.client_id,
        "redirect_uri": cfg.spotify.redirect_uri,
        "response_type": "code",
        "scope": " ".join(cfg.spotify.scopes),
        "state": token,
    }
    return RedirectResponse(f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(params)}")


@router.get("/spotify/callback")
async def spotify_callback(code: str = Query(...), state: str = Query("")):
    user = await _get_user_from_state(state)

    auth_header = base64.b64encode(
        f"{cfg.spotify.client_id}:{cfg.spotify.client_secret}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {auth_header}"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg.spotify.redirect_uri,
            },
        )
        if not resp.is_success:
            logger.error(f"Spotify token exchange failed: {resp.text}")
            raise HTTPException(400, "Failed to exchange code")
        data = resp.json()

    await set_user_credentials(user["id"], "spotify", {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "client_id": cfg.spotify.client_id,
        "client_secret": cfg.spotify.client_secret,
        "expires_in": data.get("expires_in", 3600),
    })
    logger.info(f"Spotify OAuth done for {user['email']}")
    return RedirectResponse(f"{cfg.frontend_url}/settings?connected=spotify")


# ============================================================
# Discord OAuth (for bot — we just store the bot token)
# Discord doesn't have a user OAuth flow for bots the same way,
# so we use the bot token from server config + optionally an
# OAuth2 flow for the user to add the bot to their server.
# ============================================================

@router.get("/discord")
async def discord_start(token: str = Query(...)):
    """Start Discord OAuth — adds the bot to the user's server."""
    if not cfg.discord.client_id:
        raise HTTPException(500, "DISCORD_CLIENT_ID not configured")
    _verify_state(token)

    params = {
        "client_id": cfg.discord.client_id,
        "redirect_uri": cfg.discord.redirect_uri,
        "response_type": "code",
        "scope": "identify guilds bot",
        "permissions": "274877975552",  # Send/Read messages, Read message history
        "state": token,
    }
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{urllib.parse.urlencode(params)}")


@router.get("/discord/callback")
async def discord_callback(code: str = Query(...), state: str = Query(""), guild_id: str = Query("")):
    user = await _get_user_from_state(state)

    # Exchange code for user token (to get their identity + guilds)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://discord.com/api/v10/oauth2/token",
            data={
                "client_id": cfg.discord.client_id,
                "client_secret": cfg.discord.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg.discord.redirect_uri,
            },
        )
        if not resp.is_success:
            logger.error(f"Discord token exchange failed: {resp.text}")
            raise HTTPException(400, "Failed to exchange code")
        data = resp.json()

    # Store the bot token (from server config) + user's guild info
    await set_user_credentials(user["id"], "discord", {
        "bot_token": cfg.discord.bot_token,
        "user_access_token": data.get("access_token", ""),
        "guild_id": guild_id or data.get("guild", {}).get("id", ""),
    })
    logger.info(f"Discord OAuth done for {user['email']}")
    return RedirectResponse(f"{cfg.frontend_url}/settings?connected=discord")


# ============================================================
# Mastodon OAuth
# ============================================================

@router.get("/mastodon")
async def mastodon_start(token: str = Query(...)):
    """Start Mastodon OAuth. Pass user JWT as ?token="""
    if not cfg.mastodon.client_id:
        raise HTTPException(500, "MASTODON_CLIENT_ID not configured")
    _verify_state(token)

    params = {
        "client_id": cfg.mastodon.client_id,
        "redirect_uri": cfg.mastodon.redirect_uri,
        "response_type": "code",
        "scope": " ".join(cfg.mastodon.scopes),
        "state": token,
    }
    base = cfg.mastodon.instance_url.rstrip("/")
    return RedirectResponse(f"{base}/oauth/authorize?{urllib.parse.urlencode(params)}")


@router.get("/mastodon/callback")
async def mastodon_callback(code: str = Query(...), state: str = Query("")):
    user = await _get_user_from_state(state)
    base = cfg.mastodon.instance_url.rstrip("/")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base}/oauth/token",
            data={
                "client_id": cfg.mastodon.client_id,
                "client_secret": cfg.mastodon.client_secret,
                "redirect_uri": cfg.mastodon.redirect_uri,
                "grant_type": "authorization_code",
                "code": code,
                "scope": " ".join(cfg.mastodon.scopes),
            },
        )
        if not resp.is_success:
            logger.error(f"Mastodon token exchange failed: {resp.text}")
            raise HTTPException(400, "Failed to exchange code")
        data = resp.json()

    await set_user_credentials(user["id"], "mastodon", {
        "token": data["access_token"],
        "instance_url": base,
        "scope": data.get("scope", ""),
    })
    logger.info(f"Mastodon OAuth done for {user['email']}")
    return RedirectResponse(f"{cfg.frontend_url}/settings?connected=mastodon")


# ============================================================
# Telegram Auth (MTProto — 2-step: send code, then verify)
# ============================================================

# Temporary storage for pending Telegram auth sessions
_telegram_pending: dict[int, dict] = {}


@router.post("/telegram/start")
async def telegram_start(
    api_id: str = Form(""),
    api_hash: str = Form(""),
    phone: str = Form(""),
    token: str = Form(""),
):
    """Step 1: Send a verification code to the user's phone.

    Requires api_id and api_hash from https://my.telegram.org
    """
    if not api_id or not api_hash or not phone or not token:
        raise HTTPException(400, "api_id, api_hash, phone, and token are required")

    user = await _get_user_from_state(token)

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(), int(api_id), api_hash)
    await client.connect()

    result = await client.send_code_request(phone)

    # Store pending session
    _telegram_pending[user["id"]] = {
        "client": client,
        "phone": phone,
        "api_id": api_id,
        "api_hash": api_hash,
        "phone_code_hash": result.phone_code_hash,
    }

    return {"status": "code_sent", "phone": phone}


@router.post("/telegram/verify")
async def telegram_verify(
    code: str = Form(""),
    token: str = Form(""),
):
    """Step 2: Verify the code and save the session string."""
    if not code or not token:
        raise HTTPException(400, "code and token are required")

    user = await _get_user_from_state(token)

    pending = _telegram_pending.get(user["id"])
    if not pending:
        raise HTTPException(400, "No pending Telegram auth. Call /auth/telegram/start first.")

    client = pending["client"]

    try:
        await client.sign_in(
            phone=pending["phone"],
            code=code,
            phone_code_hash=pending["phone_code_hash"],
        )

        # Save session string
        from telethon.sessions import StringSession
        session_string = client.session.save()

        await set_user_credentials(user["id"], "telegram", {
            "api_id": pending["api_id"],
            "api_hash": pending["api_hash"],
            "session_string": session_string,
        })

        logger.info(f"Telegram auth done for {user['email']}")
        return {"status": "connected"}

    except Exception as e:
        raise HTTPException(400, f"Verification failed: {e}")
    finally:
        del _telegram_pending[user["id"]]
        await client.disconnect()
