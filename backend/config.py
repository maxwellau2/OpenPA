"""Server-level configuration. User-specific keys (API tokens etc.) are stored per-user in the DB."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent


@dataclass
class LLMConfig:
    # Server-level defaults (Ollama is local, always available)
    default_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
    # User-level API keys for cloud providers are stored in DB under "llm" service


@dataclass
class GoogleOAuthConfig:
    client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    scopes: list[str] = field(default_factory=lambda: [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/calendar",
    ])


@dataclass
class GitHubOAuthConfig:
    client_id: str = os.getenv("GITHUB_CLIENT_ID", "")
    client_secret: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    redirect_uri: str = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")
    scopes: list[str] = field(default_factory=lambda: ["repo", "notifications", "read:user"])


@dataclass
class SpotifyOAuthConfig:
    client_id: str = os.getenv("SPOTIFY_CLIENT_ID", "")
    client_secret: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    redirect_uri: str = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/auth/spotify/callback")
    scopes: list[str] = field(default_factory=lambda: [
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
        "playlist-read-private",
        "streaming",
    ])


@dataclass
class DiscordOAuthConfig:
    client_id: str = os.getenv("DISCORD_CLIENT_ID", "")
    client_secret: str = os.getenv("DISCORD_CLIENT_SECRET", "")
    bot_token: str = os.getenv("DISCORD_BOT_TOKEN", "")
    redirect_uri: str = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/discord/callback")
    scopes: list[str] = field(default_factory=lambda: ["identify", "guilds", "bot"])


@dataclass
class MastodonOAuthConfig:
    client_id: str = os.getenv("MASTODON_CLIENT_ID", "")
    client_secret: str = os.getenv("MASTODON_CLIENT_SECRET", "")
    instance_url: str = os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social")
    redirect_uri: str = os.getenv("MASTODON_REDIRECT_URI", "http://localhost:8000/auth/mastodon/callback")
    scopes: list[str] = field(default_factory=lambda: ["read", "write", "push"])


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    google: GoogleOAuthConfig = field(default_factory=GoogleOAuthConfig)
    github: GitHubOAuthConfig = field(default_factory=GitHubOAuthConfig)
    spotify: SpotifyOAuthConfig = field(default_factory=SpotifyOAuthConfig)
    discord: DiscordOAuthConfig = field(default_factory=DiscordOAuthConfig)
    mastodon: MastodonOAuthConfig = field(default_factory=MastodonOAuthConfig)
    db_path: str = os.getenv("DB_PATH", str(BASE_DIR / "pa.db"))
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-production")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    version: str = os.getenv("APP_VERSION", "0.1.0")


config = Config()
