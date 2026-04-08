"""Google Gemini LLM provider via Google AI Studio."""

import json
import uuid
from typing import Any

from google import genai
from google.genai import types

from llm.base import LLMProvider, LLMResponse, Message, ToolCall


class GeminiProvider(LLMProvider):

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def _convert_messages(self, messages: list[Message]) -> list[types.Content]:
        contents = []
        for msg in messages:
            if msg.role == "tool":
                # Parse JSON result if possible, otherwise wrap as string
                try:
                    result_data = json.loads(msg.content)
                except (json.JSONDecodeError, TypeError):
                    result_data = {"result": msg.content[:2000]}
                contents.append(types.Content(
                    role="function",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name=msg.tool_call_id or "unknown",
                        response=result_data,
                    ))],
                ))
            elif msg.role == "assistant" and msg.tool_calls:
                parts = []
                if msg.content:
                    parts.append(types.Part(text=msg.content))
                for tc in msg.tool_calls:
                    parts.append(types.Part(function_call=types.FunctionCall(
                        name=tc.name, args=tc.arguments,
                    )))
                contents.append(types.Content(role="model", parts=parts))
            elif msg.role == "assistant":
                contents.append(types.Content(role="model", parts=[types.Part(text=msg.content)]))
            elif msg.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=msg.content)]))
        return contents

    def _convert_tools(self, tools: list[dict[str, Any]] | None) -> list[types.Tool] | None:
        if not tools:
            return None
        declarations = []
        for t in tools:
            params = t.get("parameters", {})
            clean = {k: v for k, v in params.items() if k != "additionalProperties"}
            declarations.append(types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", "")[:500],
                parameters=clean if clean.get("properties") else None,
            ))
        return [types.Tool(function_declarations=declarations)]

    async def chat(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None, system: str | None = None,
    ) -> LLMResponse:
        contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)

        gen_config = types.GenerateContentConfig(temperature=0.7, max_output_tokens=4096)
        if system:
            gen_config.system_instruction = system
        if gemini_tools:
            gen_config.tools = gemini_tools

        try:
            response = self.client.models.generate_content(
                model=self.model, contents=contents, config=gen_config,
            )
        except Exception as e:
            # If Gemini errors, return the error as content so the agent can handle it
            return LLMResponse(content=f"LLM error: {e}", stop_reason="error")

        content_text = None
        tool_calls = []

        if not response.candidates:
            # Gemini sometimes returns no candidates (safety filter, etc.)
            return LLMResponse(
                content=response.text if hasattr(response, 'text') and response.text else "I couldn't generate a response. Try rephrasing.",
                stop_reason="end_turn",
            )

        candidate = response.candidates[0]
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    content_text = (content_text or "") + part.text
                if part.function_call:
                    fc = part.function_call
                    tool_calls.append(ToolCall(
                        id=fc.name or str(uuid.uuid4()),
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    ))

        # If Gemini returned nothing useful, try to get text from the response object
        if not content_text and not tool_calls:
            try:
                content_text = response.text
            except Exception:
                pass

        return LLMResponse(content=content_text, tool_calls=tool_calls, stop_reason="end_turn")
