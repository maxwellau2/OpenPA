"""Authentication: password hashing, JWT tokens, user CRUD."""

import json
from datetime import datetime, timedelta, timezone

import aiosqlite
import bcrypt
import jwt

from config import config

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises jwt.InvalidTokenError on failure."""
    return jwt.decode(token, config.jwt_secret, algorithms=[JWT_ALGORITHM])


async def create_user(email: str, password: str, display_name: str = "") -> dict:
    hashed = hash_password(password)
    async with aiosqlite.connect(config.db_path) as db:
        try:
            cursor = await db.execute(
                "INSERT INTO users (email, hashed_password, display_name) VALUES (?, ?, ?)",
                (email, hashed, display_name),
            )
            await db.commit()
            return {"id": cursor.lastrowid, "email": email, "display_name": display_name}
        except aiosqlite.IntegrityError:
            raise ValueError("Email already registered")


async def authenticate_user(email: str, password: str) -> dict:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = await cursor.fetchone()

    if not user or not verify_password(password, user["hashed_password"]):
        raise ValueError("Invalid email or password")

    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, email, display_name, created_at FROM users WHERE id = ?", (user_id,)
        )
        user = await cursor.fetchone()
        return dict(user) if user else None


async def set_user_credentials(user_id: int, service: str, credentials: dict) -> dict:
    """Store credentials for a service (github, gmail, spotify, etc.)."""
    creds_json = json.dumps(credentials)
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO user_credentials (user_id, service, credentials, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id, service) DO UPDATE SET credentials=?, updated_at=CURRENT_TIMESTAMP""",
            (user_id, service, creds_json, creds_json),
        )
        await db.commit()
    return {"status": "saved", "service": service}


async def get_user_credentials(user_id: int, service: str) -> dict | None:
    """Get credentials for a specific service."""
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT credentials FROM user_credentials WHERE user_id = ? AND service = ?",
            (user_id, service),
        )
        row = await cursor.fetchone()
        return json.loads(row["credentials"]) if row else None


async def get_all_user_credentials(user_id: int) -> dict:
    """Get all credentials for a user (service names only, not the actual secrets)."""
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT service, updated_at FROM user_credentials WHERE user_id = ?",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return {"services": [{"service": r["service"], "updated_at": r["updated_at"]} for r in rows]}
