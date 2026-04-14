"""Ollama LLM provider using OpenAI-compatible API."""

import json
import uuid
from typing import Any

import httpx

from config import config
from llm.base import LLMProvider, LLMResponse, Message, ToolCall


class OllamaProvider(LLMProvider):
    """Ollama provider using its OpenAI-compatible endpoint."""

    def __init__(self, model: str = ""):
        self.base_url = config.llm.ollama_base_url
        self.model = model or config.llm.ollama_model

    def _convert_messages(
        self, messages: list[Message], system: str | None
    ) -> list[dict]:
        """Convert our Message format to OpenAI chat format."""
        result = []
        if system:
            result.append({"role": "system", "content": system})

        for msg in messages:
            if msg.role == "tool":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )
            elif msg.role == "assistant" and msg.tool_calls:
                tool_calls_formatted = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
                result.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": tool_calls_formatted,
                    }
                )
            else:
                result.append({"role": msg.role, "content": msg.content})

        return result

    def _convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict] | None:
        """Convert our tool format to OpenAI function calling format."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                },
            }
            for t in tools
        ]

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        openai_messages = self._convert_messages(messages, system)
        openai_tools = self._convert_tools(tools)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
        }
        if openai_tools:
            payload["tools"] = openai_tools

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                func = tc["function"]
                args = func.get("arguments", "{}")
                if isinstance(args, str):
                    args = json.loads(args)
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", str(uuid.uuid4())),
                        name=func["name"],
                        arguments=args,
                    )
                )

        content = message.get("content") or ""
        thinking = message.get("reasoning") or ""

        # Qwen 3.5 sometimes wraps thinking in <think> tags inside content
        import re

        think_match = re.search(
            r"<think(?:ing)?>(.*?)</think(?:ing)?>", content, re.DOTALL
        )
        if think_match:
            thinking = (thinking + "\n" + think_match.group(1)).strip()
            content = re.sub(
                r"<think(?:ing)?>.*?</think(?:ing)?>", "", content, flags=re.DOTALL
            ).strip()

        # Clean up empty strings
        content = content or None
        thinking = thinking or None

        # Qwen 3.5 sometimes puts the actual response in "reasoning" with content=null
        if not content and not tool_calls and thinking:
            content = thinking
            thinking = None

        return LLMResponse(
            content=content,
            thinking=thinking,
            tool_calls=tool_calls,
            stop_reason=choice.get("finish_reason", "stop"),
        )
