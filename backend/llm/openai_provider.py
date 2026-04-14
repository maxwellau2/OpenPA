"""OpenAI-compatible LLM provider. Used for OpenAI, OpenRouter, and any compatible API."""

import json
import uuid
from typing import Any

from openai import AsyncOpenAI

from llm.base import LLMProvider, LLMResponse, Message, ToolCall


class OpenAICompatibleProvider(LLMProvider):
    """Base provider for any OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        extra_headers: dict | None = None,
    ):
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if extra_headers:
            kwargs["default_headers"] = extra_headers
        self.client = AsyncOpenAI(**kwargs)
        self.model = model

    def _convert_messages(
        self, messages: list[Message], system: str | None
    ) -> list[dict]:
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
                tc_formatted = [
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
                        "tool_calls": tc_formatted,
                    }
                )
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result

    def _convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict] | None:
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

        kwargs: dict[str, Any] = {"model": self.model, "messages": openai_messages}
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = await self.client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                raw_args = tc.function.arguments or "{}"
                try:
                    args = (
                        json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    )
                except json.JSONDecodeError, TypeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id or str(uuid.uuid4()),
                        name=tc.function.name,
                        arguments=args if isinstance(args, dict) else {},
                    )
                )

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason or "stop",
        )


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI (GPT-4o, etc.)"""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        super().__init__(api_key=api_key, model=model)


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter — access many models through one API."""

    def __init__(self, api_key: str, model: str = "google/gemini-2.0-flash-exp:free"):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://openrouter.ai/api/v1",
            extra_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "OpenPA",
            },
        )


class GroqProvider(OpenAICompatibleProvider):
    """Groq — ultra-fast inference for open models."""

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.groq.com/openai/v1",
        )
