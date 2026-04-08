"""REST API — multi-tenant PA-as-a-Service with SSE streaming."""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastmcp import Client
from loguru import logger
from pydantic import BaseModel

from db.auth import (
    authenticate_user,
    create_token,
    create_user,
    decode_token,
    get_all_user_credentials,
    get_user,
    get_user_credentials,
    set_user_credentials,
)
from db.database import init_db
from tools.registry import mcp as mcp_server

app = FastAPI(
    title="OpenPA API",
    description="OpenPA — Personal Assistant-as-a-Service. Sign up, add your API keys, chat with your PA.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount OAuth router
from services.oauth import router as oauth_router
app.include_router(oauth_router)

_mcp_client: Client | None = None


@app.on_event("startup")
async def startup():
    global _mcp_client
    await init_db()
    _mcp_client = Client(mcp_server)
    await _mcp_client.__aenter__()
    tools = await _mcp_client.list_tools()
    logger.info(f"API started with {len(tools)} MCP tools")


@app.on_event("shutdown")
async def shutdown():
    if _mcp_client:
        await _mcp_client.__aexit__(None, None, None)


# --- Auth dependency ---


async def get_current_user(authorization: Annotated[str, Header()]) -> dict:
    """Extract and verify JWT from Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization header")
    token = authorization[7:]
    try:
        payload = decode_token(token)
        user = await get_user(payload["user_id"])
        if not user:
            raise HTTPException(401, "User not found")
        return user
    except Exception:
        raise HTTPException(401, "Invalid or expired token")


# --- Request/Response models ---


class SignupRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class ConfigRequest(BaseModel):
    credentials: dict


class ChatRequest(BaseModel):
    message: str
    provider: str = ""  # Empty = use user's default
    model: str = ""
    conversation_id: int | None = None  # Attach to existing conversation


# --- Auth endpoints ---


@app.post("/api/auth/signup")
async def signup(req: SignupRequest):
    try:
        user = await create_user(req.email, req.password, req.display_name)
        token = create_token(user["id"], user["email"])
        return {"user": user, "token": token}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    try:
        user = await authenticate_user(req.email, req.password)
        token = create_token(user["id"], user["email"])
        return {"user": user, "token": token}
    except ValueError as e:
        raise HTTPException(401, str(e))


@app.get("/api/me")
async def me(user: dict = Depends(get_current_user)):
    services = await get_all_user_credentials(user["id"])
    return {"user": user, "connected_services": services}


# --- Per-user config endpoints ---


@app.put("/api/config/{service}")
async def save_config(service: str, req: ConfigRequest, user: dict = Depends(get_current_user)):
    """Save API credentials for a service."""
    valid_services = {"github", "gmail", "google", "spotify", "discord", "telegram", "mastodon"}
    if service not in valid_services:
        raise HTTPException(400, f"Invalid service. Must be one of: {valid_services}")
    result = await set_user_credentials(user["id"], service, req.credentials)
    return result


@app.get("/api/config")
async def list_config(user: dict = Depends(get_current_user)):
    """List which services the user has configured."""
    return await get_all_user_credentials(user["id"])


@app.get("/api/config/{service}")
async def get_config(service: str, user: dict = Depends(get_current_user)):
    """Get credentials for a specific service."""
    creds = await get_user_credentials(user["id"], service)
    if not creds:
        raise HTTPException(404, f"No credentials for {service}")
    return {"service": service, "credentials": creds}


# --- Conversation history endpoints ---


@app.get("/api/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    """List user's saved conversations."""
    import aiosqlite
    from config import config as cfg
    async with aiosqlite.connect(cfg.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC LIMIT 50",
            (user["id"],),
        )
        rows = await cursor.fetchall()
    return {"conversations": [{k: row[k] for k in row.keys()} for row in rows]}


@app.post("/api/conversations")
async def create_conversation(user: dict = Depends(get_current_user)):
    """Create a new conversation."""
    import aiosqlite
    from config import config as cfg
    async with aiosqlite.connect(cfg.db_path) as db:
        cursor = await db.execute(
            "INSERT INTO conversations (user_id) VALUES (?)", (user["id"],),
        )
        await db.commit()
        return {"id": cursor.lastrowid, "title": "New Chat"}


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: int, user: dict = Depends(get_current_user)):
    """Get messages for a conversation."""
    import aiosqlite
    from config import config as cfg
    async with aiosqlite.connect(cfg.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content, created_at FROM conversation_history WHERE conversation_id = ? AND user_id = ? ORDER BY created_at",
            (conv_id, user["id"]),
        )
        rows = await cursor.fetchall()
    return {"messages": [{k: row[k] for k in row.keys()} for row in rows]}


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: int, user: dict = Depends(get_current_user)):
    """Delete a conversation."""
    import aiosqlite
    from config import config as cfg
    async with aiosqlite.connect(cfg.db_path) as db:
        await db.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"]),
        )
        await db.commit()
    return {"status": "deleted"}


# --- Tool endpoints ---


@app.get("/api/tools")
async def list_tools():
    """List all available tools and their schemas."""
    tools = await _mcp_client.list_tools()
    return {
        "tools": [
            {"name": t.name, "description": t.description, "parameters": t.inputSchema}
            for t in tools
        ]
    }


@app.post("/api/tools/{tool_name}")
async def call_tool(tool_name: str, arguments: dict = {}, user: dict = Depends(get_current_user)):
    """Call any MCP tool directly."""
    arguments["_user_id"] = user["id"]
    try:
        result = await _mcp_client.call_tool(tool_name, arguments)
        return {"tool": tool_name, "result": result.data}
    except Exception as e:
        raise HTTPException(400, str(e))


# --- LLM provider endpoints ---


@app.get("/api/llm/providers")
async def llm_providers():
    """List available LLM providers and their models."""
    from llm.providers import PROVIDERS
    return {"providers": PROVIDERS}


@app.get("/api/llm/config")
async def get_llm_config(user: dict = Depends(get_current_user)):
    """Get user's LLM provider config (which keys are set, default provider)."""
    creds = await get_user_credentials(user["id"], "llm") or {}
    return {
        "default_provider": creds.get("default_provider", "ollama"),
        "default_model": creds.get("default_model", ""),
        "configured_providers": [
            k.replace("_api_key", "") for k in creds if k.endswith("_api_key") and creds[k]
        ],
    }


class LLMConfigRequest(BaseModel):
    default_provider: str = ""
    default_model: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    claude_api_key: str = ""
    openrouter_api_key: str = ""


@app.put("/api/llm/config")
async def save_llm_config(req: LLMConfigRequest, user: dict = Depends(get_current_user)):
    """Save user's LLM provider config and API keys."""
    # Merge with existing (don't overwrite keys that weren't provided)
    existing = await get_user_credentials(user["id"], "llm") or {}
    updates = req.model_dump(exclude_unset=False)
    for key, value in updates.items():
        if value:  # Only update non-empty values
            existing[key] = value
    await set_user_credentials(user["id"], "llm", existing)
    return {"status": "saved"}


# --- Chat endpoints ---


@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    """Send a message to the PA (non-streaming)."""
    from llm.agent import Agent
    from llm.providers import get_llm_provider
    from prompts.system import SYSTEM_PROMPT

    provider = await get_llm_provider(user["id"], req.provider, req.model)
    agent = Agent(
        provider=provider,
        system_prompt=SYSTEM_PROMPT,
        mcp_client=_mcp_client,
        user_id=user["id"],
    )
    response = await agent.run(req.message)
    return {"response": response}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, user: dict = Depends(get_current_user)):
    """Send a message to the PA with SSE streaming."""
    from llm.agent import Agent, AgentEvent
    from llm.base import Message
    from llm.providers import get_llm_provider
    from prompts.system import SYSTEM_PROMPT
    from db.conversations import (
        get_or_create_conversation, load_messages, save_message,
        update_conversation_title, compact_conversation,
    )

    try:
        provider = await get_llm_provider(user["id"], req.provider, req.model)
    except ValueError as e:
        async def error_gen():
            yield AgentEvent("error", {"error": str(e)}).to_sse()
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    conv_id = await get_or_create_conversation(user["id"], req.conversation_id, req.message)

    agent = Agent(
        provider=provider,
        system_prompt=SYSTEM_PROMPT,
        mcp_client=_mcp_client,
        user_id=user["id"],
    )

    async def event_generator():
        # Compact if conversation is getting long
        compacted = await compact_conversation(user["id"], conv_id, provider)
        if compacted:
            yield AgentEvent("compacted", {"conversation_id": conv_id}).to_sse()

        # Load conversation history from DB and seed the agent
        prior_messages = await load_messages(user["id"], conv_id)
        for msg in prior_messages:
            agent.conversation.append(Message(role=msg["role"], content=msg["content"]))

        await save_message(user["id"], conv_id, "user", req.message)

        assistant_response = ""
        try:
            async for event in agent.run_stream(req.message):
                if event.type == "done":
                    assistant_response = event.data.get("response", "")
                    event.data["conversation_id"] = conv_id
                yield event.to_sse()
        except Exception as e:
            yield AgentEvent("error", {"error": str(e)}).to_sse()

        if assistant_response:
            await save_message(user["id"], conv_id, "assistant", assistant_response)
            await update_conversation_title(conv_id, req.message)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
