"""Google Gemini LLM provider via Google AI Studio."""

import json
import uuid
from typing import Any

from google import genai
from google.genai import types
from loguru import logger

from llm.base import LLMProvider, LLMResponse, Message, ToolCall


UNSUPPORTED_SCHEMA_KEYS = {"additionalProperties", "$schema", "default"}


def _strip_unsupported_keys(obj: Any) -> Any:
    """Recursively remove keys that Gemini doesn't accept in tool schemas."""
    if isinstance(obj, dict):
        return {
            k: _strip_unsupported_keys(v)
            for k, v in obj.items()
            if k not in UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(obj, list):
        return [_strip_unsupported_keys(item) for item in obj]
    return obj


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def _convert_messages(self, messages: list[Message]) -> list[types.Content]:
        contents = []
        for msg in messages:
            if msg.role == "tool":
                # Parse JSON result if possible, otherwise wrap as string
                try:
                    result_data = json.loads(msg.content)
                except json.JSONDecodeError, TypeError:
                    result_data = {"result": msg.content[:2000]}
                contents.append(
                    types.Content(
                        role="function",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=msg.tool_call_id or "unknown",
                                    response=result_data,
                                )
                            )
                        ],
                    )
                )
            elif msg.role == "assistant" and msg.tool_calls:
                parts = []
                if msg.content:
                    parts.append(types.Part(text=msg.content))
                for tc in msg.tool_calls:
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=tc.name,
                                args=tc.arguments,
                            )
                        )
                    )
                contents.append(types.Content(role="model", parts=parts))
            elif msg.role == "assistant":
                contents.append(
                    types.Content(role="model", parts=[types.Part(text=msg.content)])
                )
            elif msg.role == "user":
                contents.append(
                    types.Content(role="user", parts=[types.Part(text=msg.content)])
                )
        return contents

    def _convert_tools(
        self, tools: list[dict[str, Any]] | None
    ) -> list[types.Tool] | None:
        if not tools:
            return None
        declarations = []
        for t in tools:
            try:
                params = t.get("parameters", {})
                clean = _strip_unsupported_keys(params)
                # Gemini requires properties with defined types — convert bare "object" to "string"
                props = clean.get("properties", {})
                for pname, pval in list(props.items()):
                    if (
                        isinstance(pval, dict)
                        and pval.get("type") == "object"
                        and "properties" not in pval
                    ):
                        # Gemini can't handle free-form objects — treat as JSON string
                        props[pname] = {
                            "type": "string",
                            "description": pval.get(
                                "description", f"{pname} as JSON string"
                            ),
                        }
                declarations.append(
                    types.FunctionDeclaration(
                        name=t["name"],
                        description=t.get("description", "")[:500],
                        parameters=clean if props else None,
                    )
                )
            except Exception as e:
                logger.warning(
                    f"Skipping tool {t.get('name', '?')} — failed to convert: {e}"
                )
                continue
        return (
            [types.Tool(function_declarations=declarations)] if declarations else None
        )

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)

        gen_config = types.GenerateContentConfig(
            temperature=0.4, max_output_tokens=16384
        )
        if system:
            gen_config.system_instruction = system
        if gemini_tools:
            gen_config.tools = gemini_tools

        try:
            tool_count = 0
            if gemini_tools:
                try:
                    tool_count = len(gemini_tools[0].function_declarations or [])
                except Exception:
                    pass
            logger.debug(
                f"Gemini request: {len(contents)} messages, {tool_count} tools"
            )
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=gen_config,
            )
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return LLMResponse(content=f"LLM error: {e}", stop_reason="error")

        content_text = None
        tool_calls = []

        if not response.candidates:
            logger.warning(
                f"Gemini returned no candidates. Prompt feedback: {getattr(response, 'prompt_feedback', None)}"
            )
            return LLMResponse(
                content=response.text
                if hasattr(response, "text") and response.text
                else "I couldn't generate a response. Try rephrasing.",
                stop_reason="end_turn",
            )

        candidate = response.candidates[0]
        logger.debug(
            f"Gemini candidate finish_reason: {candidate.finish_reason}, parts: {len(candidate.content.parts) if candidate.content and candidate.content.parts else 0}"
        )
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    content_text = (content_text or "") + part.text
                if part.function_call:
                    fc = part.function_call
                    tool_calls.append(
                        ToolCall(
                            id=fc.name or str(uuid.uuid4()),
                            name=fc.name,
                            arguments=dict(fc.args) if fc.args else {},
                        )
                    )

        # If Gemini returned nothing useful, try to get text from the response object
        if not content_text and not tool_calls:
            try:
                content_text = response.text
            except Exception:
                pass

        # Gemini 2.5 sometimes returns empty parts — retry once without tools to force a text response
        if not content_text and not tool_calls and gemini_tools:
            logger.warning(
                "Gemini returned empty with tools — retrying without tools to force text response"
            )
            try:
                gen_config_no_tools = types.GenerateContentConfig(
                    temperature=0.4, max_output_tokens=16384
                )
                if system:
                    gen_config_no_tools.system_instruction = system
                retry_response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=gen_config_no_tools,
                )
                if retry_response.candidates:
                    rc = retry_response.candidates[0]
                    if rc.content and rc.content.parts:
                        for part in rc.content.parts:
                            if part.text:
                                content_text = (content_text or "") + part.text
            except Exception as e:
                logger.error(f"Gemini retry failed: {e}")

        logger.info(
            f"Gemini response: content={'yes' if content_text else 'EMPTY'} ({len(content_text or '')} chars), tool_calls={len(tool_calls)}"
        )
        return LLMResponse(
            content=content_text, tool_calls=tool_calls, stop_reason="end_turn"
        )
