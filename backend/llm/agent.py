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
MAX_ITERATIONS_WORKSPACE = 50  # More room for coding tasks with test-fix loops

# Tool categories for context-aware filtering
TOOL_CATEGORIES = {
    "core": {
        "memory_get_preferences", "memory_set_preference", "memory_remember_about_user",
        "memory_get_user_memories", "memory_forget_about_user", "memory_save_note",
        "memory_search_history", "memory_get_recent_conversations",
    },
    "workspace": {
        "ws_workspace_create", "ws_workspace_list_files", "ws_workspace_read_file",
        "ws_workspace_write_file", "ws_workspace_edit_file", "ws_workspace_delete_file",
        "ws_workspace_grep", "ws_workspace_find", "ws_workspace_run",
        "ws_workspace_diff", "ws_workspace_commit_push", "ws_workspace_cleanup",
        "ws_workspace_inspect", "ws_workspace_check_syntax", "ws_workspace_install",
    },
    "github": {
        "github_create_repo", "github_list_repos", "github_list_prs", "github_get_pr_diff",
        "github_create_issue", "github_create_pr", "github_create_branch",
        "github_list_files", "github_get_file", "github_push_file",
        "github_list_notifications",
    },
    "communication": {
        "discord_list_servers", "discord_list_channels", "discord_send_message",
        "discord_read_messages", "telegram_search_contacts", "telegram_send_message",
        "telegram_list_chats", "telegram_read_messages",
        "gmail_get_unread", "gmail_read_email", "gmail_send_email", "gmail_reply_email",
    },
    "media": {
        "spotify_play", "spotify_pause", "spotify_current_track",
        "spotify_search", "spotify_get_playlists",
        "youtube_download_video", "youtube_get_video_info",
    },
    "web": {
        "web_search", "scrape_fetch_page", "scrape_fetch_tables", "scrape_fetch_links",
    },
    "social": {
        "mastodon_get_home_timeline", "mastodon_get_public_timeline",
        "mastodon_get_trending_tags", "mastodon_get_trending_statuses",
        "mastodon_search_posts", "mastodon_get_hashtag_timeline",
        "mastodon_post_status", "mastodon_get_notifications", "mastodon_get_account_info",
    },
    "productivity": {
        "calendar_list_events", "calendar_create_event", "calendar_delete_event",
        "rss_fetch_feed", "rss_fetch_all_feeds", "rss_add_feed", "rss_list_feeds",
        "scheduler_schedule_task", "scheduler_list_scheduled_tasks",
        "scheduler_cancel_scheduled_task",
    },
    "sandbox": {
        "sandbox_verify_python", "sandbox_verify_javascript",
        "sandbox_run_python", "sandbox_run_javascript",
        "sandbox_run_multi_file_test", "sandbox_run_shell", "sandbox_run_and_export",
    },
}

# Keywords that hint which categories are needed
CATEGORY_KEYWORDS = {
    "workspace": ["add feature", "add a ", "fix bug", "modify", "refactor", "implement", "workspace", "branch", "vibe", "code", "build", "endpoint", "tool", "component"],
    "github": ["pr", "pull request", "repo", "commit", "push", "issue", "github", "branch", "endpoint", "feature"],
    "communication": ["send", "message", "discord", "telegram", "email", "gmail", "reply", "briefing", "notification"],
    "media": ["play", "music", "spotify", "song", "youtube", "video", "download"],
    "web": ["search", "find online", "look up", "web", "scrape", "fetch page", "website"],
    "social": ["mastodon", "toot", "trending", "fediverse", "timeline"],
    "productivity": ["calendar", "event", "schedule", "rss", "feed", "remind", "briefing", "daily"],
    "sandbox": ["run code", "execute", "python", "javascript", "test code", "sandbox"],
}


def _select_tool_categories(user_message: str, tools_called: list[str]) -> set[str]:
    """Select which tool categories to include based on context."""
    categories = {"core"}  # Always include core/memory tools
    msg_lower = user_message.lower()

    # Match by keywords in user message
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in msg_lower for kw in keywords):
            categories.add(cat)

    # If workspace tools were already called, keep them + github for PR
    if any(t.startswith("ws_") for t in tools_called):
        categories.update({"workspace", "github", "web"})

    # If no specific category matched, just use core — the LLM can still answer
    # conversationally, and will request tools if it needs them

    return categories

PLANNER_PROMPT = """You are a task planner. Given the user's request and the available tools, decide if this needs multiple steps.

If the request involves CODING, WORKSPACE, or VIBE-CODING (adding features, fixing bugs, modifying repos, writing code), ALWAYS output:
{"simple": true}
These tasks MUST use the adaptive loop so you can react to test failures and fix issues dynamically.

If the request needs MULTIPLE steps and is NOT a coding task (e.g., fetch data then send it somewhere), output a plan as a JSON array:

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

    async def _build_system_prompt(self, user_message: str = "") -> str:
        """Build system prompt with auto-injected user context and RAG-retrieved memories."""
        # Base context (user info, services, preferences) is cached
        if not self._system_prompt_built:
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

        # RAG: retrieve relevant memories for this specific message
        if user_message:
            try:
                from services.rag import retrieve_relevant_memories
                memories = await retrieve_relevant_memories(self.user_id, user_message, top_k=10)
                if memories:
                    mem_lines = [f"  - [{m['category']}] {m['content']} (relevance: {m['relevance']})" for m in memories]
                    memory_section = f"\n\n## What you know about this user (retrieved by relevance to current message)\n" + "\n".join(mem_lines)
                    return self._system_prompt_built + memory_section
            except Exception:
                pass

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

            # Trim description to first sentence to save tokens
            desc = t.description or ""
            first_sentence_end = desc.find(". ")
            short_desc = desc[:first_sentence_end + 1] if first_sentence_end > 0 else desc[:150]

            self._tools_cache.append({
                "name": t.name,
                "description": short_desc,
                "parameters": schema,
            })

        logger.info(f"Loaded {len(self._tools_cache)} tools from MCP server")
        return self._tools_cache

    def _filter_tools(self, tools: list[dict], categories: set[str]) -> list[dict]:
        """Filter tools to only include relevant categories."""
        allowed = set()
        for cat in categories:
            allowed.update(TOOL_CATEGORIES.get(cat, set()))

        filtered = [t for t in tools if t["name"] in allowed]
        logger.info(f"Filtered tools: {len(filtered)}/{len(tools)} (categories: {categories})")
        return filtered

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
        tool_lines = []
        for t in tools:
            params = t.get("parameters", {}).get("properties", {})
            param_names = [k for k in params.keys() if k != "_user_id"]
            param_str = f"({', '.join(param_names)})" if param_names else "()"
            tool_lines.append(f"- {t['name']}{param_str}: {t['description'][:80]}")
        tool_list = "\n".join(tool_lines)

        # Include recent conversation context so the planner understands references like "it", "that", etc.
        context = ""
        recent = [m for m in self.conversation[-6:] if m.role in ("user", "assistant") and m.content]
        if len(recent) > 1:  # Only if there's actual history
            context = "Recent conversation:\n"
            for m in recent[:-1]:  # Exclude current message
                context += f"  {m.role}: {m.content[:300]}\n"
            context += "\n"

        plan_messages = [
            Message(role="user", content=f"Available tools:\n{tool_list}\n\n{context}User request: {user_message}")
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
        all_tools = await self._get_tools()
        system_prompt = await self._build_system_prompt(user_message)

        # Filter tools based on task context to avoid overwhelming smaller models
        categories = _select_tool_categories(user_message, [])
        tools = self._filter_tools(all_tools, categories)
        # Fallback: if filtering left too few tools, use all
        if len(tools) < 3:
            tools = all_tools

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

                # Replace ALL template placeholders that reference a previous step number
                # Catches: {{step_4_result}}, {{step_4.output}}, {{depends_on.4}}, {{result_4}}, etc.
                import re
                args_str = json.dumps(args)
                for prev_step, prev_result in step_results.items():
                    short_result = prev_result[:4000]
                    safe_result = short_result.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", "")
                    # Match any {{...}} that contains this step number
                    pattern = r"\{\{[^}]*\b" + str(prev_step) + r"\b[^}]*\}\}"
                    args_str = re.sub(pattern, safe_result, args_str)

                # Safety net: replace ANY remaining {{...}} with the most recent step result
                if "{{" in args_str and step_results:
                    last_result = list(step_results.values())[-1][:4000]
                    safe_last = last_result.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", "")
                    args_str = re.sub(r"\{\{[^}]*\}\}", safe_last, args_str)
                    logger.warning(f"Replaced leftover {{{{...}}}} templates with last step result")

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
                        else:
                            # Clean up: if the result looks like JSON, skip it — only inject human-readable text
                            clean_prev = prev.strip()
                            if clean_prev.startswith("{") or clean_prev.startswith("["):
                                # Try to extract a meaningful text field from JSON
                                try:
                                    import json as _json
                                    parsed = _json.loads(clean_prev)
                                    if isinstance(parsed, dict):
                                        for key in ("content", "message", "text", "result", "summary"):
                                            if key in parsed and isinstance(parsed[key], str):
                                                clean_prev = parsed[key]
                                                break
                                except Exception:
                                    pass
                            # Inject into the first empty text-like field
                            for field in ("content", "message", "body", "text", "prompt"):
                                if field in args and args[field] == "":
                                    args[field] = clean_prev[:4000]
                                    break

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

        # === SIMPLE EXECUTION (adaptive agent loop) ===
        iterations = 0
        tools_called: list[str] = []  # Track what we've done to keep the agent focused
        is_workspace_task = False  # Detected dynamically when workspace tools are called
        while iterations < (MAX_ITERATIONS_WORKSPACE if is_workspace_task else MAX_ITERATIONS):
            iterations += 1
            if iterations > 1:
                yield AgentEvent("thinking", {"iteration": iterations})

            # Inject a progress reminder every few iterations to prevent drift
            max_iter = MAX_ITERATIONS_WORKSPACE if is_workspace_task else MAX_ITERATIONS
            effective_system = system_prompt
            if tools_called and iterations > 3 and iterations % 3 == 0:
                progress = ", ".join(tools_called[-10:])
                workspace_hint = ""
                if is_workspace_task:
                    workspace_hint = (
                        "\nYou are in a WORKSPACE coding session. Follow the adaptive workflow: "
                        "if tests/build fail, read the error, fix the code, and re-test. "
                        "Do NOT give up or push broken code. Loop until green."
                    )
                effective_system = (
                    f"{system_prompt}\n\n## Progress so far\n"
                    f"Original request: {user_message}\n"
                    f"Tools called: {progress}\n"
                    f"Iteration: {iterations}/{max_iter} — stay focused on the original request."
                    f"{workspace_hint}"
                )

            response: LLMResponse = await self.provider.chat(
                messages=self.conversation,
                tools=tools if tools else None,
                system=effective_system,
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
                    tools_called.append(tool_call.name)
                    if tool_call.name.startswith("ws_") and not is_workspace_task:
                        is_workspace_task = True
                        # Re-filter tools to include workspace + github + web
                        categories = _select_tool_categories(user_message, tools_called)
                        tools = self._filter_tools(all_tools, categories)
                        logger.info("Switched to workspace mode — expanded tool set")

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
