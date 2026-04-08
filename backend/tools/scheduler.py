"""Task scheduler — schedule tool calls to execute at a future time."""

import asyncio
import time
import uuid
from datetime import datetime, timezone

from fastmcp import FastMCP
from loguru import logger

mcp = FastMCP("scheduler")

# In-memory job store: {job_id: {tool, args, run_at, user_id, status, result}}
_jobs: dict[str, dict] = {}
_running_tasks: dict[str, asyncio.Task] = {}

# Reference to MCP client — set by the REST API on startup
_mcp_client = None


def set_mcp_client(client):
    """Called by rest_api.py on startup to give the scheduler access to tools."""
    global _mcp_client
    _mcp_client = client
    logger.info(f"Scheduler MCP client set: {client is not None}")


@mcp.tool()
async def schedule_task(
    _user_id: int,
    tool_name: str,
    tool_args: str,
    delay_minutes: float = 0,
    run_at: str = "",
    description: str = "",
) -> dict:
    """Schedule a tool call to execute in the future. Use this for reminders, delayed messages, timed actions.

    Either provide delay_minutes (e.g., 60 = one hour from now) OR run_at (ISO datetime like "2026-04-09T17:00:00").

    Args:
        _user_id: User ID (injected automatically)
        tool_name: The tool to call (e.g., "telegram_send_message", "gmail_send_email", "discord_send_message")
        tool_args: JSON string of the tool arguments (e.g., '{"to": "Mom", "message": "Meeting reminder!"}')
        delay_minutes: Minutes from now to execute (use this OR run_at)
        run_at: ISO datetime to execute at (e.g., "2026-04-09T17:00:00") — use this OR delay_minutes
        description: Human-readable description of the job (e.g., "Remind Mom about meeting")
    """
    import json

    if not delay_minutes and not run_at:
        return {"error": "Provide either delay_minutes or run_at"}

    # Parse run time
    if run_at:
        try:
            run_time = datetime.fromisoformat(run_at)
            if run_time.tzinfo is None:
                run_time = run_time.replace(tzinfo=timezone.utc)
        except ValueError:
            return {"error": f"Invalid datetime format: {run_at}. Use ISO format like 2026-04-09T17:00:00"}
    else:
        run_time = datetime.now(timezone.utc).replace(microsecond=0)
        run_time = run_time.__class__.fromtimestamp(run_time.timestamp() + delay_minutes * 60, tz=timezone.utc)

    # Parse tool args
    try:
        args = json.loads(tool_args) if isinstance(tool_args, str) else tool_args
    except json.JSONDecodeError:
        return {"error": f"tool_args must be valid JSON, got: {tool_args[:200]}"}

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "tool": tool_name,
        "args": args,
        "run_at": run_time.isoformat(),
        "user_id": _user_id,
        "description": description or f"Run {tool_name}",
        "status": "scheduled",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
    }

    # Schedule the async task
    delay_seconds = max(0, (run_time - datetime.now(timezone.utc)).total_seconds())
    task = asyncio.create_task(_execute_job(job_id, delay_seconds, _user_id))
    _running_tasks[job_id] = task

    logger.info(f"Scheduled job {job_id}: {tool_name} in {delay_seconds:.0f}s ({description})")

    return {
        "job_id": job_id,
        "tool": tool_name,
        "run_at": run_time.isoformat(),
        "delay_minutes": round(delay_seconds / 60, 1),
        "description": description or f"Run {tool_name}",
        "status": "scheduled",
    }


@mcp.tool()
async def list_scheduled_tasks(_user_id: int) -> dict:
    """List all scheduled tasks for the current user.

    Args:
        _user_id: User ID (injected automatically)
    """
    user_jobs = [
        {
            "job_id": jid,
            "tool": job["tool"],
            "description": job["description"],
            "run_at": job["run_at"],
            "status": job["status"],
            "result": job["result"][:200] if job["result"] else None,
        }
        for jid, job in _jobs.items()
        if job["user_id"] == _user_id
    ]
    return {"jobs": user_jobs, "count": len(user_jobs)}


@mcp.tool()
async def cancel_scheduled_task(_user_id: int, job_id: str) -> dict:
    """Cancel a scheduled task.

    Args:
        _user_id: User ID (injected automatically)
        job_id: The job ID to cancel
    """
    job = _jobs.get(job_id)
    if not job:
        return {"error": f"Job {job_id} not found"}
    if job["user_id"] != _user_id:
        return {"error": "Not your job"}
    if job["status"] != "scheduled":
        return {"error": f"Job is already {job['status']}"}

    task = _running_tasks.pop(job_id, None)
    if task:
        task.cancel()
    job["status"] = "cancelled"

    return {"job_id": job_id, "status": "cancelled"}


async def _execute_job(job_id: str, delay_seconds: float, user_id: int):
    """Wait for delay, then execute the tool call."""
    try:
        await asyncio.sleep(delay_seconds)

        job = _jobs.get(job_id)
        if not job or job["status"] != "scheduled":
            return

        if not _mcp_client:
            job["status"] = "failed"
            job["result"] = "MCP client not available — scheduler was not initialized"
            logger.error(f"Job {job_id}: MCP client not set")
            return

        job["status"] = "running"
        logger.info(f"Executing scheduled job {job_id}: {job['tool']}({job['args']})")

        full_args = {**job["args"], "_user_id": user_id}
        try:
            result = await _mcp_client.call_tool(job["tool"], full_args)
        except Exception as e:
            job["status"] = "failed"
            job["result"] = f"Tool execution failed: {e}"
            logger.error(f"Job {job_id} tool call failed: {e}")
            return

        if hasattr(result, "data") and result.data is not None:
            import json
            job["result"] = json.dumps(result.data, default=str)[:1000]
        elif hasattr(result, "content") and result.content:
            job["result"] = "\n".join(c.text for c in result.content if hasattr(c, "text"))[:1000]
        else:
            job["result"] = str(result)[:1000]

        job["status"] = "completed"
        logger.info(f"Job {job_id} completed: {job['result'][:200]}")

    except asyncio.CancelledError:
        _jobs[job_id]["status"] = "cancelled"
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["result"] = str(e)[:1000]
    finally:
        _running_tasks.pop(job_id, None)
