"""Telegram bot — primary chat interface for the PA.

Users link their account by sending /login <email> <password>.
After linking, all messages go through the agent loop with their user context.
"""

from loguru import logger
from fastmcp import Client
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import config
from db.auth import authenticate_user, set_user_credentials
from llm.agent import Agent
from llm.base import LLMProvider
from prompts.system import SYSTEM_PROMPT

# One agent per chat (keyed by chat_id)
_agents: dict[int, Agent] = {}

# Map telegram chat_id → PA user_id (loaded from DB or set via /login)
_chat_user_map: dict[int, int] = {}

# Set by main.py at startup
_provider: LLMProvider | None = None
_mcp_client: Client | None = None


def set_provider(provider: LLMProvider):
    global _provider
    _provider = provider


def set_mcp_client(client: Client):
    global _mcp_client
    _mcp_client = client


def _get_agent(chat_id: int, user_id: int) -> Agent:
    if chat_id not in _agents:
        _agents[chat_id] = Agent(
            provider=_provider,
            system_prompt=SYSTEM_PROMPT,
            mcp_client=_mcp_client,
            user_id=user_id,
        )
    return _agents[chat_id]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey! I'm your Personal Assistant.\n\n"
        "First, link your account:\n"
        "/login <email> <password>\n\n"
        "Then ask me anything:\n"
        "- 'check my emails'\n"
        "- 'give me a daily briefing'\n"
        "- 'review my open PRs'\n"
        "- 'play some focus music'\n\n"
        "/reset to clear conversation history"
    )


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Link a Telegram chat to a PA account: /login email password"""
    chat_id = update.effective_chat.id
    args = context.args

    if not args or len(args) < 2:
        await update.message.reply_text("Usage: /login <email> <password>")
        return

    email, password = args[0], args[1]

    try:
        user = await authenticate_user(email, password)
        _chat_user_map[chat_id] = user["id"]

        # Also store the mapping in DB so it persists across restarts
        await set_user_credentials(user["id"], "telegram", {"chat_id": str(chat_id)})

        # Delete the login message for security
        try:
            await update.message.delete()
        except Exception:
            pass

        await update.effective_chat.send_message(
            f"Logged in as {user['email']}! Your messages are now connected to your PA.\n"
            "Try: 'give me a daily briefing'"
        )
    except ValueError as e:
        await update.message.reply_text(f"Login failed: {e}")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in _agents:
        _agents[chat_id].reset()
    await update.message.reply_text("Conversation reset!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _provider or not _mcp_client:
        await update.message.reply_text("PA is starting up, try again in a moment.")
        return

    chat_id = update.effective_chat.id

    if chat_id not in _chat_user_map:
        await update.message.reply_text(
            "Please link your account first: /login <email> <password>"
        )
        return

    user_id = _chat_user_map[chat_id]
    user_text = update.message.text
    agent = _get_agent(chat_id, user_id)

    await update.message.chat.send_action("typing")

    try:
        response = await agent.run(user_text)
        if len(response) > 4000:
            for i in range(0, len(response), 4000):
                await update.message.reply_text(response[i : i + 4000])
        else:
            await update.message.reply_text(response)
    except Exception as e:
        logger.opt(exception=True).error("Error in agent loop")
        await update.message.reply_text(f"Something went wrong: {e}")


def create_telegram_app() -> Application:
    app = Application.builder().token(config.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app
