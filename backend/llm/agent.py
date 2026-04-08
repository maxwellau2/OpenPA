"""The agent loop — uses MCP client to discover and call tools.

Uses a plan-then-execute approach for complex multi-step tasks.
The LLM first creates a plan, then executes each step one at a time.
"""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from loguru import logger
from fastmcp import Client

from llm.base import LLMProvider, LLMResponse, Message

MAX_ITERATIONS = 30

PLANNER_PROMPT = """You are a task planner. Given the user's request and the available tools, decide if this needs multiple steps.

If the request needs MULTIPLE steps, output a plan as a JSON array. Each step is either a tool call OR a text generation (for things like writing, summarizing, composing):

[
  {"step": 1, "description": "Fetch trending Mastodon tags", "tool": "mastodon_get_trending_tags", "args": {}},
  {"step": 2, "description": "Compose a human-readable summary of the trends", "tool": "llm_generate", "args": {"prompt": "Summarize these Mastodon trends into a short, readable message."}, "depends_on": 1},
  {"step": 3, "description": "Send the summary to Discord general", "tool": "discord_send_message", "args": {"channel_name": "general", "content": ""}, "depends_on": 2}
]

Use "depends_on": N to pass the result of step N as context into the current step.

Use "llm_generate" as the tool name when the step requires writing, summarizing, composing, or any text generation that doesn't need an external API.
Use actual tool names for steps that need external services.

If a step needs to reference the output of a previous step, add a "depends_on" field with the step number instead of using template placeholders.
When a step needs to send/post/share results from earlier steps, use "llm_generate" to compose a human-readable summary first, then send that summary.

If the request is SIMPLE (one tool call, or just a question/conversation), output:
{"simple": true}

ONLY output valid JSON, nothing else."""


@dataclass
class AgentEvent:
    """An event emitted during the agent loop for SSE streaming."""
    type: str  # "thinking", "tool_call", "tool_result", "planning", "step", "done", "error"
    data: dict

    def to_sse(self) -> str:
        return f"event: {self.type}\ndata: {json.dumps(self.data, default=str)}\n\n"


class Agent:
    """Agent that loops between LLM reasoning and MCP tool execution."""

    def __init__(self, provider: LLMProvider, system_prompt: str, mcp_client: Client, user_id: int):
        self.provider = provider
        self.system_prompt = system_prompt
        self.mcp_client = mcp_client
        self.user_id = user_id
        self.conversation: list[Message] = []
        self._tools_cache: list[dict] | None = None
        self._context_loaded = False
        self._system_prompt_built: str | None = None

    async def _build_system_prompt(self) -> str:
        """Build system prompt with auto-injected user context."""
        if self._system_prompt_built:
            return self._system_prompt_built

        context_parts = []

        try:
            from db.auth import get_all_user_credentials, get_user
            user = await get_user(self.user_id)
            if user:
                context_parts.append(f"Current user: {user['email']}")

            services = await get_all_user_credentials(self.user_id)
            connected = [s["service"] for s in services.get("services", [])]
            if connected:
                context_parts.append(f"Connected services: {', '.join(connected)}")
            else:
                context_parts.append("No services connected yet.")
        except Exception:
            pass

        try:
            result = await self.mcp_client.call_tool(
                "memory_get_preferences", {"_user_id": self.user_id}
            )
            if hasattr(result, 'data') and result.data:
                prefs = result.data.get("preferences", [])
                if prefs:
                    pref_lines = [f"  - {p['key']}: {p['value']}" for p in prefs[:20]]
                    context_parts.append(f"User preferences:\n" + "\n".join(pref_lines))
        except Exception:
            pass

        if context_parts:
            context = "\n".join(context_parts)
            self._system_prompt_built = f"{self.system_prompt}\n\n## Current User Context\n{context}"
        else:
            self._system_prompt_built = self.system_prompt

        return self._system_prompt_built

    async def _get_tools(self) -> list[dict]:
        """Fetch tool definitions from the MCP server."""
        if self._tools_cache is not None:
            return self._tools_cache

        mcp_tools = await self.mcp_client.list_tools()
        self._tools_cache = []
        for t in mcp_tools:
            schema = dict(t.inputSchema) if t.inputSchema else {"type": "object", "properties": {}}
            props = dict(schema.get("properties", {}))
            props.pop("_user_id", None)
            schema["properties"] = props
            req = [r for r in schema.get("required", []) if r != "_user_id"]
            if req:
                schema["required"] = req
            elif "required" in schema:
                del schema["required"]

            self._tools_cache.append({
                "name": t.name,
                "description": t.description or "",
                "parameters": schema,
            })

        logger.info(f"Loaded {len(self._tools_cache)} tools from MCP server")
        return self._tools_cache

    async def _call_tool(self, name: str, args: dict) -> str:
        """Execute a tool and return the result as text."""
        full_args = {**args, "_user_id": self.user_id}
        try:
            result = await self.mcp_client.call_tool(name, full_args)
            if hasattr(result, 'data') and result.data is not None:
                return json.dumps(result.data, indent=2, default=str)
            elif hasattr(result, 'content') and result.content:
                return "\n".join(c.text for c in result.content if hasattr(c, 'text'))
            return str(result)
        except Exception as e:
            logger.opt(exception=True).error(f"Tool {name} failed")
            return f"Error: {e}"

    async def _try_plan(self, user_message: str, tools: list[dict]) -> list[dict] | None:
        """Ask the LLM to create a plan. Returns list of steps or None if simple."""
        tool_names = [f"- {t['name']}: {t['description'][:80]}" for t in tools]
        tool_list = "\n".join(tool_names)

        plan_messages = [
            Message(role="user", content=f"Available tools:\n{tool_list}\n\nUser request: {user_message}")
        ]

        response = await self.provider.chat(
            messages=plan_messages,
            tools=None,  # No tools for planning — just text output
            system=PLANNER_PROMPT,
        )

        text = (response.content or "").strip()
        # Strip think tags
        import re
        text = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", text, flags=re.DOTALL).strip()

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("simple"):
                return None
            if isinstance(parsed, list) and len(parsed) > 1:
                return parsed
        except (json.JSONDecodeError, KeyError):
            pass

        return None

    async def run(self, user_message: str) -> str:
        """Process a user message (non-streaming). Returns final text."""
        result = ""
        async for event in self.run_stream(user_message):
            if event.type == "done":
                result = event.data.get("response", "")
            elif event.type == "error":
                result = event.data.get("error", "Something went wrong.")
        return result

    async def run_stream(self, user_message: str) -> AsyncGenerator[AgentEvent, None]:
        """Process a user message, yielding events for SSE streaming.

        Flow:
        1. Ask LLM if this needs a multi-step plan
        2. If yes → execute plan step by step, each step = one tool call
        3. If no → normal agent loop (LLM decides tools)
        4. Final: LLM summarizes all results
        """
        self.conversation.append(Message(role="user", content=user_message))
        tools = await self._get_tools()
        system_prompt = await self._build_system_prompt()

        # Step 1: Try to create a plan
        yield AgentEvent("thinking", {"iteration": 1})
        plan = await self._try_plan(user_message, tools)

        if plan and len(plan) > 1:
            # === PLANNED EXECUTION ===
            yield AgentEvent("planning", {
                "steps": [{"step": s.get("step", i+1), "description": s.get("description", "")} for i, s in enumerate(plan)]
            })

            step_results: dict[int, str] = {}

            for i, step in enumerate(plan):
                step_num = step.get("step", i + 1)
                tool_name = step.get("tool", "")
                args = step.get("args", {})
                description = step.get("description", f"Step {step_num}")

                yield AgentEvent("step", {"step": step_num, "description": description, "tool": tool_name})

                # Replace {{step_N_result}} and {{step_N_result.field}} placeholders
                import re
                args_str = json.dumps(args)
                for prev_step, prev_result in step_results.items():
                    short_result = prev_result[:500]
                    safe_result = short_result.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", "")
                    # Match {{step_N_result}} and {{step_N_result.anything}}
                    pattern = r"\{\{\s*step_" + str(prev_step) + r"_result(?:\.\w+)*\s*\}\}"
                    args_str = re.sub(pattern, safe_result, args_str)
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = step.get("args", {})

                # Handle depends_on: inject previous result(s) into args for context
                depends_on = step.get("depends_on")
                if depends_on is not None:
                    # Normalize to list of step numbers
                    dep_list = depends_on if isinstance(depends_on, list) else [depends_on]
                    prev_parts = []
                    for dep in dep_list:
                        if dep in step_results:
                            prev_parts.append(step_results[dep][:2000])
                    if prev_parts:
                        prev = "\n\n".join(prev_parts)
                        if tool_name == "llm_generate":
                            args["prompt"] = args.get("prompt", "") + f"\n\nContext from previous steps:\n{prev}"
                        elif "content" in args and args["content"] == "":
                            args["content"] = prev[:500]

                yield AgentEvent("tool_call", {"tool": tool_name, "arguments": args})

                # Handle llm_generate pseudo-tool (text generation without external API)
                if tool_name == "llm_generate":
                    prompt = args.get("prompt", description)
                    gen_response = await self.provider.chat(
                        messages=[Message(role="user", content=prompt)],
                        tools=None,
                        system="You are a helpful assistant. Respond directly to the request. Be concise.",
                    )
                    result_text = gen_response.content or ""
                else:
                    result_text = await self._call_tool(tool_name, args)

                step_results[step_num] = result_text

                logger.info(f"Plan step {step_num} ({tool_name}): {result_text[:200]}...")
                yield AgentEvent("tool_result", {"tool": tool_name, "result_preview": result_text[:300]})

            # Final: ask LLM to summarize all results
            summary_content = "I executed the following plan:\n"
            for i, step in enumerate(plan):
                step_num = step.get("step", i + 1)
                summary_content += f"\nStep {step_num}: {step.get('description', '')}\n"
                summary_content += f"Result: {step_results.get(step_num, 'No result')[:500]}\n"

            self.conversation.append(Message(role="assistant", content=summary_content))
            self.conversation.append(Message(role="user", content="Now summarize the results concisely for me."))

            yield AgentEvent("thinking", {"iteration": 2})
            response = await self.provider.chat(
                messages=self.conversation,
                tools=None,
                system=system_prompt,
            )

            if response.thinking:
                yield AgentEvent("thinking_text", {"text": response.thinking})

            final_text = response.content or summary_content
            self.conversation.append(Message(role="assistant", content=final_text))
            yield AgentEvent("done", {"response": final_text})
            return

        # === SIMPLE EXECUTION (normal agent loop) ===
        iterations = 0
        while iterations < MAX_ITERATIONS:
            iterations += 1
            if iterations > 1:
                yield AgentEvent("thinking", {"iteration": iterations})

            response: LLMResponse = await self.provider.chat(
                messages=self.conversation,
                tools=tools if tools else None,
                system=system_prompt,
            )

            if response.thinking:
                yield AgentEvent("thinking_text", {"text": response.thinking})

            if response.has_tool_calls:
                self.conversation.append(Message(
                    role="assistant",
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                ))

                for tool_call in response.tool_calls:
                    logger.info(f"Calling MCP tool: {tool_call.name}({tool_call.arguments})")

                    yield AgentEvent("tool_call", {
                        "tool": tool_call.name,
                        "arguments": tool_call.arguments,
                    })

                    result_text = await self._call_tool(tool_call.name, tool_call.arguments)

                    logger.info(f"Tool result: {result_text[:200]}...")
                    yield AgentEvent("tool_result", {
                        "tool": tool_call.name,
                        "result_preview": result_text[:300],
                    })

                    self.conversation.append(Message(
                        role="tool",
                        content=result_text,
                        tool_call_id=tool_call.id,
                    ))

                continue

            final_text = response.content
            if not final_text:
                # LLM returned empty after tool calls — nudge it to summarize
                self.conversation.append(Message(role="user", content="Please summarize the tool results above concisely for the user."))
                try:
                    nudge_response = await self.provider.chat(
                        messages=self.conversation, tools=None, system=system_prompt,
                    )
                    final_text = nudge_response.content
                except Exception as e:
                    logger.error(f"Nudge failed: {e}")

            if not final_text:
                # Fall back to the last tool result if LLM still returned nothing
                for msg in reversed(self.conversation):
                    if msg.role == "tool" and msg.content:
                        final_text = msg.content
                        logger.info("Falling back to raw tool result")
                        break

            final_text = final_text or "(No response)"
            self.conversation.append(Message(role="assistant", content=final_text))
            yield AgentEvent("done", {"response": final_text})
            return

        yield AgentEvent("done", {"response": "I've reached the maximum number of steps."})

    def reset(self):
        """Clear conversation history."""
        self.conversation = []

    def invalidate_tools(self):
        """Force re-fetching tools from MCP server."""
        self._tools_cache = None
