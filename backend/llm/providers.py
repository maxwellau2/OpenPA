"""LLM provider factory — creates the right provider based on user's chosen config."""

from db.auth import get_user_credentials
from llm.base import LLMProvider

# Available providers and their default models
PROVIDERS = {
    "ollama": {
        "label": "Ollama (Local)",
        "description": "Free, runs locally. Requires Ollama installed.",
        "models": ["qwen3.5:9b", "llama3.1:8b", "mistral:7b"],
        "needs_api_key": False,
    },
    "gemini": {
        "label": "Google Gemini",
        "description": "Free tier: 15 req/min. Excellent tool calling.",
        "models": ["gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-2.5-pro"],
        "needs_api_key": True,
        "key_field": "api_key",
        "get_key_url": "https://aistudio.google.com/apikey",
    },
    "openai": {
        "label": "OpenAI",
        "description": "GPT-4o, GPT-4o-mini. Pay-per-token.",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
        "needs_api_key": True,
        "key_field": "api_key",
        "get_key_url": "https://platform.openai.com/api-keys",
    },
    "claude": {
        "label": "Anthropic Claude",
        "description": "Best tool calling. Pay-per-token.",
        "models": ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
        "needs_api_key": True,
        "key_field": "api_key",
        "get_key_url": "https://console.anthropic.com/settings/keys",
    },
    "openrouter": {
        "label": "OpenRouter",
        "description": "Access many models through one API. Some free models available.",
        "models": ["google/gemini-2.0-flash-exp:free", "meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen3-8b:free"],
        "needs_api_key": True,
        "key_field": "api_key",
        "get_key_url": "https://openrouter.ai/keys",
    },
}


async def get_llm_provider(user_id: int, provider: str = "", model: str = "") -> LLMProvider:
    """Create an LLM provider based on user's choice and stored credentials.

    Args:
        user_id: The user's ID (for looking up API keys)
        provider: Provider name (ollama, gemini, openai, claude, openrouter)
        model: Model name override (optional)
    """
    # Get user's LLM config from DB
    llm_config = await get_user_credentials(user_id, "llm") or {}

    # Use specified provider, or user's default, or server default
    if not provider:
        provider = llm_config.get("default_provider", "")
    if not provider:
        from config import config
        provider = config.llm.default_provider

    if provider == "ollama":
        from llm.ollama_provider import OllamaProvider
        return OllamaProvider(model=model)

    elif provider == "gemini":
        api_key = llm_config.get("gemini_api_key", "")
        if not api_key:
            raise ValueError("No Gemini API key configured. Go to Settings → LLM Providers to add one.")
        from llm.gemini_provider import GeminiProvider
        return GeminiProvider(api_key=api_key, model=model or "gemini-2.5-flash")

    elif provider == "openai":
        api_key = llm_config.get("openai_api_key", "")
        if not api_key:
            raise ValueError("No OpenAI API key configured. Go to Settings → LLM Providers to add one.")
        from llm.openai_provider import OpenAIProvider
        return OpenAIProvider(api_key=api_key, model=model or "gpt-4o-mini")

    elif provider == "claude":
        api_key = llm_config.get("claude_api_key", "")
        if not api_key:
            raise ValueError("No Claude API key configured. Go to Settings → LLM Providers to add one.")
        from llm.claude_provider import ClaudeProvider
        return ClaudeProvider(api_key=api_key, model=model or "claude-sonnet-4-20250514")

    elif provider == "openrouter":
        api_key = llm_config.get("openrouter_api_key", "")
        if not api_key:
            raise ValueError("No OpenRouter API key configured. Go to Settings → LLM Providers to add one.")
        from llm.openrouter_provider import OpenRouterProvider
        return OpenRouterProvider(api_key=api_key, model=model or "google/gemini-2.0-flash-exp:free")

    else:
        raise ValueError(f"Unknown provider: {provider}")
