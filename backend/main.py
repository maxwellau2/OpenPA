"""Personal Assistant-as-a-Service — main entry point."""

import asyncio

from loguru import logger
from fastmcp import Client

from config import config
from db.database import init_db
from llm.agent import Agent
from llm.base import LLMProvider
from prompts.system import SYSTEM_PROMPT
from tools.registry import mcp as mcp_server


def get_provider() -> LLMProvider:
    """Create the LLM provider based on config."""
    if config.llm.default_provider == "claude":
        from llm.claude_provider import ClaudeProvider
        return ClaudeProvider()
    else:
        from llm.ollama_provider import OllamaProvider
        return OllamaProvider()


async def run_cli():
    """Run the PA in interactive CLI mode (for testing)."""
    await init_db()
    provider = get_provider()

    # Create or get a default CLI user
    from db.auth import create_user, authenticate_user
    try:
        user = await create_user("cli@local", "cli", "CLI User")
        logger.info(f"Created CLI user: {user['email']}")
    except ValueError:
        user = await authenticate_user("cli@local", "cli")
        logger.info(f"Using existing CLI user: {user['email']}")

    user_id = user["id"]

    logger.info(f"Using LLM provider: {config.llm.default_provider}")
    logger.info(f"Model: {config.llm.ollama_model if config.llm.default_provider == 'ollama' else config.llm.claude_model}")

    async with Client(mcp_server) as mcp_client:
        tools = await mcp_client.list_tools()
        logger.info(f"Loaded {len(tools)} MCP tools: {[t.name for t in tools]}")

        agent = Agent(provider=provider, system_prompt=SYSTEM_PROMPT, mcp_client=mcp_client, user_id=user_id)

        print("\n=== Personal Assistant ===")
        print(f"Logged in as: {user['email']}")
        print("Type your message (or 'quit' to exit, 'reset' to clear history)\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break

            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("Bye!")
                break
            if user_input.lower() == "reset":
                agent.reset()
                print("Conversation reset.\n")
                continue

            response = await agent.run(user_input)
            print(f"\nAssistant: {response}\n")


async def run_telegram():
    """Run the PA as a Telegram bot."""
    await init_db()
    provider = get_provider()

    logger.info(f"Starting Telegram bot with {config.llm.default_provider} provider")

    async with Client(mcp_server) as mcp_client:
        tools = await mcp_client.list_tools()
        logger.info(f"Loaded {len(tools)} MCP tools")

        from chat.telegram_bot import create_telegram_app, set_mcp_client, set_provider
        set_provider(provider)
        set_mcp_client(mcp_client)

        app = create_telegram_app()
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        logger.info("Telegram bot is running. Press Ctrl+C to stop.")
        try:
            await asyncio.Event().wait()  # Run forever
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


async def run_mcp_server():
    """Run as a standalone MCP server (stdio transport)."""
    await init_db()
    logger.info("Starting MCP server (stdio)")
    await mcp_server.run_stdio_async()


def run_api():
    """Run the REST API server."""
    import uvicorn
    from services.rest_api import app
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"

    if mode == "cli":
        asyncio.run(run_cli())
    elif mode == "telegram":
        asyncio.run(run_telegram())
    elif mode == "mcp":
        asyncio.run(run_mcp_server())
    elif mode == "api":
        run_api()
    else:
        print(f"Unknown mode: {mode}")
        print("Usage: python main.py [cli|telegram|mcp|api]")
        sys.exit(1)
