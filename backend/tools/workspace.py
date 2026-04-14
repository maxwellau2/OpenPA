"""Workspace tools — clone repos, edit files, run tests/builds, and push changes.

Provides a local git workspace for the agent to develop features end-to-end:
clone → explore → edit → test → fix → commit → push → PR.
"""

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastmcp import FastMCP
from loguru import logger

from tools.credentials import get_creds

mcp = FastMCP("workspace")

TIMEOUT_SECONDS = 120  # 2 min for builds/tests
MAX_OUTPUT_CHARS = 15000
WORKSPACE_EXPIRY = 3600  # 1 hour

# Active workspaces: {workspace_id: {path, repo, branch, user_id, created_at}}
_workspaces: dict[str, dict] = {}


def _cleanup_expired():
    now = time.time()
    expired = [
        k for k, v in _workspaces.items() if now - v["created_at"] > WORKSPACE_EXPIRY
    ]
    for k in expired:
        path = _workspaces[k]["path"]
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
        del _workspaces[k]
        logger.info(f"Cleaned up expired workspace {k}")


def _get_workspace(workspace_id: str, user_id: int) -> dict:
    _cleanup_expired()
    ws = _workspaces.get(workspace_id)
    if not ws:
        raise RuntimeError(
            f"Workspace '{workspace_id}' not found. Create one first with workspace_create."
        )
    if ws["user_id"] != user_id:
        raise RuntimeError("Access denied.")
    return ws


async def _run(cmd: str, cwd: str, timeout: int = TIMEOUT_SECONDS) -> dict:
    """Run a shell command in the workspace."""
    env = os.environ.copy()
    # Filter secrets but keep git/npm/node stuff
    for key in list(env.keys()):
        if any(
            s in key.upper() for s in ["SECRET", "PASSWORD", "API_KEY", "CREDENTIAL"]
        ):
            del env[key]

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout": stdout.decode(errors="replace")[:MAX_OUTPUT_CHARS],
            "stderr": stderr.decode(errors="replace")[:MAX_OUTPUT_CHARS],
        }
    except asyncio.TimeoutError:
        return {
            "exit_code": -1,
            "passed": False,
            "stdout": "",
            "stderr": f"Timed out after {timeout}s",
        }


# ── Workspace lifecycle ──────────────────────────────────────────────


@mcp.tool()
async def workspace_create(_user_id: int, repo: str, branch: str = "") -> dict:
    """Clone a GitHub repo into a temporary workspace and optionally create a feature branch.
    This is the first step for any code modification workflow.

    Args:
        _user_id: User ID (injected automatically)
        repo: GitHub repo in 'owner/name' format (e.g. 'maxwellau2/OpenPA')
        branch: Branch name to create (e.g. 'feature/new-tool'). If empty, stays on default branch.
    """
    creds = await get_creds(_user_id, "github")
    token = creds["token"]

    workspace_id = str(uuid.uuid4())[:8]
    workspace_dir = os.path.join(tempfile.gettempdir(), f"workspace_{workspace_id}")
    os.makedirs(workspace_dir, exist_ok=True)

    # Full clone (not shallow) so PRs work correctly
    clone_url = f"https://x-access-token:{token}@github.com/{repo}.git"
    result = await _run(f"git clone '{clone_url}' repo", workspace_dir, timeout=120)
    if not result["passed"]:
        shutil.rmtree(workspace_dir, ignore_errors=True)
        return {"error": f"Clone failed: {result['stderr']}"}

    repo_dir = os.path.join(workspace_dir, "repo")

    # Configure git user
    await _run("git config user.email 'openpa-bot@users.noreply.github.com'", repo_dir)
    await _run("git config user.name 'OpenPA Bot'", repo_dir)

    created_branch = ""
    if branch:
        result = await _run(f"git checkout -b '{branch}'", repo_dir)
        if not result["passed"]:
            # Branch might already exist remotely
            result = await _run(f"git checkout '{branch}'", repo_dir)
        created_branch = branch

    _workspaces[workspace_id] = {
        "path": repo_dir,
        "workspace_dir": workspace_dir,
        "repo": repo,
        "branch": created_branch or "default",
        "user_id": _user_id,
        "created_at": time.time(),
        "token": token,
    }

    # Get default branch name and basic repo info
    default_br = await _run("git rev-parse --abbrev-ref HEAD", repo_dir)
    default_branch = default_br["stdout"].strip() if not created_branch else ""
    if not default_branch:
        # If we created a branch, find the base branch
        db = await _run(
            "git remote show origin | grep 'HEAD branch' | awk '{print $NF}'", repo_dir
        )
        default_branch = db["stdout"].strip() or "main"

    tree = await _run(
        "find . -maxdepth 2 -not -path './.git/*' -not -path './.git' | head -50",
        repo_dir,
    )

    logger.info(
        f"Created workspace {workspace_id} for {repo} (branch: {created_branch or default_branch}, default: {default_branch})"
    )
    return {
        "workspace_id": workspace_id,
        "repo": repo,
        "branch": created_branch or default_branch,
        "default_branch": default_branch,
        "structure": tree["stdout"],
    }


@mcp.tool()
async def workspace_cleanup(_user_id: int, workspace_id: str) -> dict:
    """Delete a workspace and all its files.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID to delete
    """
    ws = _get_workspace(workspace_id, _user_id)
    shutil.rmtree(ws["workspace_dir"], ignore_errors=True)
    del _workspaces[workspace_id]
    return {"status": "cleaned up", "workspace_id": workspace_id}


# ── File exploration ─────────────────────────────────────────────────


@mcp.tool()
async def workspace_list_files(
    _user_id: int, workspace_id: str, path: str = ".", max_depth: int = 3
) -> dict:
    """List files and directories in the workspace. Like 'tree' or 'ls -R'.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        path: Relative path within the repo (default: root)
        max_depth: How deep to list (default 3)
    """
    ws = _get_workspace(workspace_id, _user_id)
    target = os.path.join(ws["path"], path)
    result = await _run(
        f"find '{target}' -maxdepth {max_depth} -not -path '*/.git/*' -not -path '*/.git' -not -path '*/node_modules/*' -not -path '*/__pycache__/*' | sort | head -200",
        ws["path"],
    )
    return {"files": result["stdout"]}


@mcp.tool()
async def workspace_read_file(_user_id: int, workspace_id: str, path: str) -> dict:
    """Read a file from the workspace.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        path: Relative path to the file (e.g. 'backend/tools/github.py')
    """
    ws = _get_workspace(workspace_id, _user_id)
    full_path = os.path.join(ws["path"], path)
    if not os.path.isfile(full_path):
        return {"error": f"File not found: {path}"}
    try:
        content = Path(full_path).read_text(errors="replace")
        return {"path": path, "content": content[:50000], "size": len(content)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def workspace_write_file(
    _user_id: int, workspace_id: str, path: str, content: str
) -> dict:
    """Write or create a file in the workspace. Creates parent directories if needed.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        path: Relative path (e.g. 'backend/tools/new_tool.py')
        content: Full file content to write
    """
    ws = _get_workspace(workspace_id, _user_id)
    full_path = os.path.join(ws["path"], path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    Path(full_path).write_text(content)
    return {"status": "written", "path": path, "size": len(content)}


@mcp.tool()
async def workspace_edit_file(
    _user_id: int, workspace_id: str, path: str, old_text: str, new_text: str
) -> dict:
    """Edit a file by replacing a specific text block. More precise than rewriting the whole file.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        path: Relative path to the file
        old_text: The exact text to find and replace
        new_text: The replacement text
    """
    ws = _get_workspace(workspace_id, _user_id)
    full_path = os.path.join(ws["path"], path)
    if not os.path.isfile(full_path):
        return {"error": f"File not found: {path}"}

    content = Path(full_path).read_text(errors="replace")
    count = content.count(old_text)
    if count == 0:
        return {"error": "old_text not found in file", "path": path}
    if count > 1:
        return {
            "error": f"old_text found {count} times — provide more context to make it unique",
            "path": path,
        }

    new_content = content.replace(old_text, new_text, 1)
    Path(full_path).write_text(new_content)
    return {"status": "edited", "path": path, "replacements": 1}


@mcp.tool()
async def workspace_delete_file(_user_id: int, workspace_id: str, path: str) -> dict:
    """Delete a file from the workspace.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        path: Relative path to the file
    """
    ws = _get_workspace(workspace_id, _user_id)
    full_path = os.path.join(ws["path"], path)
    if not os.path.exists(full_path):
        return {"error": f"File not found: {path}"}
    os.remove(full_path)
    return {"status": "deleted", "path": path}


# ── Search ───────────────────────────────────────────────────────────


@mcp.tool()
async def workspace_grep(
    _user_id: int, workspace_id: str, pattern: str, path: str = ".", include: str = ""
) -> dict:
    """Search for a pattern in workspace files using grep. Supports regex.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        pattern: Search pattern (regex supported)
        path: Directory to search in (default: repo root)
        include: File glob filter (e.g. '*.py', '*.tsx')
    """
    ws = _get_workspace(workspace_id, _user_id)
    target = os.path.join(ws["path"], path)

    include_flag = f"--include='{include}'" if include else ""
    cmd = f"grep -rn --color=never {include_flag} '{pattern}' '{target}' | head -100"
    # Strip workspace path prefix from output for cleaner results
    result = await _run(cmd, ws["path"])

    # Clean up absolute paths to relative
    repo_prefix = ws["path"] + "/"
    clean_output = result["stdout"].replace(repo_prefix, "")

    return {"matches": clean_output, "pattern": pattern}


@mcp.tool()
async def workspace_find(
    _user_id: int, workspace_id: str, pattern: str, path: str = "."
) -> dict:
    """Find files by name pattern (glob). Like 'find . -name pattern'.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        pattern: Filename pattern (e.g. '*.py', 'test_*', '*.tsx')
        path: Directory to search in (default: repo root)
    """
    ws = _get_workspace(workspace_id, _user_id)
    target = os.path.join(ws["path"], path)
    result = await _run(
        f"find '{target}' -name '{pattern}' -not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/__pycache__/*' | sort | head -100",
        ws["path"],
    )

    repo_prefix = ws["path"] + "/"
    clean_output = result["stdout"].replace(repo_prefix, "")
    return {"files": clean_output, "pattern": pattern}


# ── Run commands / tests / builds ────────────────────────────────────


@mcp.tool()
async def workspace_run(
    _user_id: int, workspace_id: str, command: str, timeout: int = 120
) -> dict:
    """Run a shell command in the workspace. Use for tests, builds, linting, etc.

    Examples: 'cd backend && pytest', 'cd frontend && npm run build',
    'cd backend && ruff check tools/', 'npm install', 'pip install -e .'

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        command: Shell command to execute
        timeout: Timeout in seconds (default 120, max 300)
    """
    ws = _get_workspace(workspace_id, _user_id)
    timeout = min(timeout, 300)
    result = await _run(command, ws["path"], timeout=timeout)

    # Always extract errors/warnings from output to help the agent focus
    combined = result["stdout"] + "\n" + result["stderr"]
    errors = _extract_errors(combined)
    if errors:
        result["errors_summary"] = errors

    return result


def _extract_errors(output: str) -> list[str]:
    """Extract the most relevant error lines from test/build output."""
    errors = []
    lines = output.split("\n")
    for i, line in enumerate(lines):
        lower = line.lower()
        # Python errors
        if any(
            p in lower
            for p in [
                "error:",
                "failed",
                "traceback",
                "assert",
                "importerror",
                "syntaxerror",
                "nameerror",
                "typeerror",
                "attributeerror",
                "modulenotfounderror",
                "keyerror",
                "valueerror",
                "indentationerror",
            ]
        ):
            # Grab the error line + up to 2 lines of context after
            context = lines[i : i + 3]
            errors.append("\n".join(context).strip())
        # JS/TS errors
        elif any(
            p in lower
            for p in [
                "error ts",
                "error:",
                "cannot find",
                "is not assignable",
                "module not found",
                "syntaxerror",
                "referenceerror",
                "type error",
                "build failed",
            ]
        ):
            context = lines[i : i + 3]
            errors.append("\n".join(context).strip())
        # pytest summary
        elif line.startswith("FAILED ") or line.startswith("E "):
            errors.append(line.strip())

    # Deduplicate and limit
    seen = set()
    unique = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique[:15]


# ── Git operations ───────────────────────────────────────────────────


@mcp.tool()
async def workspace_diff(_user_id: int, workspace_id: str) -> dict:
    """Show git diff of all changes made in the workspace (staged + unstaged).

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
    """
    ws = _get_workspace(workspace_id, _user_id)
    # Show both staged and unstaged, plus untracked files
    diff = await _run("git diff HEAD", ws["path"])
    status = await _run("git status --short", ws["path"])
    untracked = await _run("git ls-files --others --exclude-standard", ws["path"])
    return {
        "diff": diff["stdout"][:MAX_OUTPUT_CHARS],
        "status": status["stdout"],
        "untracked_files": untracked["stdout"],
    }


@mcp.tool()
async def workspace_commit_push(_user_id: int, workspace_id: str, message: str) -> dict:
    """Stage all changes, commit, and push to the remote branch.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        message: Commit message
    """
    ws = _get_workspace(workspace_id, _user_id)
    repo_dir = ws["path"]

    # Stage all changes
    await _run("git add -A", repo_dir)

    # Commit
    result = await _run(f"git commit -m '{message}'", repo_dir)
    if not result["passed"]:
        if "nothing to commit" in result["stdout"]:
            return {"status": "nothing to commit"}
        return {"error": f"Commit failed: {result['stderr']}"}

    # Push
    branch = ws["branch"]
    if branch == "default":
        # Get current branch name
        br = await _run("git rev-parse --abbrev-ref HEAD", repo_dir)
        branch = br["stdout"].strip()

    result = await _run(f"git push origin '{branch}'", repo_dir, timeout=60)
    if not result["passed"]:
        # Try setting upstream
        result = await _run(f"git push -u origin '{branch}'", repo_dir, timeout=60)
        if not result["passed"]:
            return {"error": f"Push failed: {result['stderr']}"}

    commit_sha = await _run("git rev-parse --short HEAD", repo_dir)

    # Auto-cleanup workspace after successful push
    shutil.rmtree(ws["workspace_dir"], ignore_errors=True)
    del _workspaces[workspace_id]
    logger.info(f"Auto-cleaned workspace {workspace_id} after push")

    return {
        "status": "pushed",
        "branch": branch,
        "commit": commit_sha["stdout"].strip(),
        "message": message,
        "workspace": "auto-cleaned",
    }


# ── Code inspection ──────────────────────────────────────────────────

_PYTHON_INSPECT_SCRIPT = """
import ast, sys, json

path = sys.argv[1]
with open(path) as f:
    tree = ast.parse(f.read())

result = {"imports": [], "classes": [], "functions": [], "constants": []}

for node in ast.iter_child_nodes(tree):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        module = node.module if isinstance(node, ast.ImportFrom) else None
        for alias in node.names:
            name = f"from {module} import {alias.name}" if module else f"import {alias.name}"
            result["imports"].append(name)
    elif isinstance(node, ast.ClassDef):
        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = []
                for a in item.args.args:
                    ann = ""
                    if a.annotation:
                        try: ann = f": {ast.unparse(a.annotation)}"
                        except: pass
                    args.append(f"{a.arg}{ann}")
                ret = ""
                if item.returns:
                    try: ret = f" -> {ast.unparse(item.returns)}"
                    except: pass
                doc = ast.get_docstring(item) or ""
                prefix = "async " if isinstance(item, ast.AsyncFunctionDef) else ""
                methods.append({"name": item.name, "signature": f"{prefix}def {item.name}({', '.join(args)}){ret}", "docstring": doc[:200]})
        bases = []
        for b in node.bases:
            try: bases.append(ast.unparse(b))
            except: pass
        result["classes"].append({"name": node.name, "bases": bases, "methods": methods, "docstring": (ast.get_docstring(node) or "")[:200]})
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = []
        for a in node.args.args:
            ann = ""
            if a.annotation:
                try: ann = f": {ast.unparse(a.annotation)}"
                except: pass
            args.append(f"{a.arg}{ann}")
        ret = ""
        if node.returns:
            try: ret = f" -> {ast.unparse(node.returns)}"
            except: pass
        doc = ast.get_docstring(node) or ""
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        result["functions"].append({"name": node.name, "signature": f"{prefix}def {node.name}({', '.join(args)}){ret}", "docstring": doc[:200]})
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id.isupper():
                try: result["constants"].append({"name": t.id, "value": ast.unparse(node.value)[:100]})
                except: pass

print(json.dumps(result, indent=2))
"""


@mcp.tool()
async def workspace_inspect(_user_id: int, workspace_id: str, path: str) -> dict:
    """Inspect a Python file's structure — extract all classes, functions, their signatures,
    constructors, docstrings, and imports. Use this to understand an API before using it.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        path: Relative path to a Python file (e.g. 'backend/tools/github.py')
    """
    ws = _get_workspace(workspace_id, _user_id)
    full_path = os.path.join(ws["path"], path)
    if not os.path.isfile(full_path):
        return {"error": f"File not found: {path}"}

    if path.endswith(".py"):
        # Use AST-based introspection for Python
        import json as _json

        script_path = os.path.join(ws["workspace_dir"], "_inspect.py")
        Path(script_path).write_text(_PYTHON_INSPECT_SCRIPT)
        result = await _run(f"python3 '{script_path}' '{full_path}'", ws["path"])
        if result["passed"]:
            try:
                return {
                    "path": path,
                    "language": "python",
                    **_json.loads(result["stdout"]),
                }
            except Exception:
                return {"path": path, "raw": result["stdout"]}
        return {"error": result["stderr"]}

    elif path.endswith((".ts", ".tsx", ".js", ".jsx")):
        # For JS/TS, use grep-based extraction (no Node AST dependency needed)
        patterns = {
            "exports": "grep -n 'export ' '{full_path}' | head -30",
            "functions": "grep -nE '(function |const |async function |export (default )?function )' '{full_path}' | head -30",
            "classes": "grep -nE '(class |interface |type )' '{full_path}' | head -20",
            "imports": "grep -n 'import ' '{full_path}' | head -30",
        }
        result = {}
        for key, cmd in patterns.items():
            r = await _run(cmd.replace("{full_path}", full_path), ws["path"])
            result[key] = r["stdout"].strip().split("\n") if r["stdout"].strip() else []
        return {"path": path, "language": "typescript/javascript", **result}

    else:
        return {"error": f"Inspection not supported for this file type: {path}"}


@mcp.tool()
async def workspace_check_syntax(_user_id: int, workspace_id: str, path: str) -> dict:
    """Check a file for syntax errors, linting issues, and type problems.
    Python: uses py_compile + ruff. JS/TS: uses the project's tsc/eslint if available.

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        path: Relative path to the file to check
    """
    ws = _get_workspace(workspace_id, _user_id)
    full_path = os.path.join(ws["path"], path)
    if not os.path.isfile(full_path):
        return {"error": f"File not found: {path}"}

    checks = []

    if path.endswith(".py"):
        # Syntax check
        result = await _run(f"python3 -m py_compile '{full_path}'", ws["path"])
        checks.append(
            {"check": "syntax", "passed": result["passed"], "output": result["stderr"]}
        )
        # Ruff lint
        result = await _run(f"ruff check '{full_path}'", ws["path"])
        checks.append(
            {
                "check": "ruff",
                "passed": result["passed"],
                "output": result["stdout"] + result["stderr"],
            }
        )

    elif path.endswith((".ts", ".tsx")):
        # TypeScript check if tsc available
        result = await _run(
            f"cd '{os.path.dirname(full_path)}' && npx tsc --noEmit '{full_path}' 2>&1 || true",
            ws["path"],
        )
        checks.append(
            {
                "check": "typescript",
                "passed": "error" not in result["stdout"].lower(),
                "output": result["stdout"],
            }
        )

    elif path.endswith((".js", ".jsx")):
        # Node syntax check
        result = await _run(f"node --check '{full_path}'", ws["path"])
        checks.append(
            {"check": "syntax", "passed": result["passed"], "output": result["stderr"]}
        )

    all_passed = all(c["passed"] for c in checks) if checks else False
    return {"path": path, "passed": all_passed, "checks": checks}


# ── Dependency management ────────────────────────────────────────────


@mcp.tool()
async def workspace_install(
    _user_id: int, workspace_id: str, packages: str, dev: bool = False
) -> dict:
    """Install packages in the workspace. Auto-detects Python (pip/uv) or Node (npm).

    Args:
        _user_id: User ID (injected automatically)
        workspace_id: The workspace ID
        packages: Space-separated package names (e.g. 'requests beautifulsoup4' or 'axios lodash')
        dev: Install as dev dependency (default false)
    """
    ws = _get_workspace(workspace_id, _user_id)
    repo_dir = ws["path"]

    # Detect project type
    has_pyproject = os.path.exists(os.path.join(repo_dir, "pyproject.toml"))
    has_requirements = os.path.exists(os.path.join(repo_dir, "requirements.txt"))
    has_package_json = os.path.exists(os.path.join(repo_dir, "package.json"))
    has_frontend = os.path.exists(os.path.join(repo_dir, "frontend", "package.json"))

    results = []

    if has_pyproject:
        # Try uv first, fall back to pip
        uv_check = await _run("which uv", repo_dir)
        if uv_check["passed"]:
            cmd = f"uv add {packages}"
            if dev:
                cmd = f"uv add --dev {packages}"
        else:
            cmd = f"pip install {packages}"
        result = await _run(cmd, repo_dir, timeout=120)
        results.append({"type": "python", "command": cmd, **result})
    elif has_requirements:
        result = await _run(f"pip install {packages}", repo_dir, timeout=120)
        results.append(
            {"type": "python", "command": f"pip install {packages}", **result}
        )

    if has_package_json:
        flag = "--save-dev" if dev else ""
        result = await _run(f"npm install {flag} {packages}", repo_dir, timeout=120)
        results.append(
            {"type": "node", "command": f"npm install {flag} {packages}", **result}
        )
    elif has_frontend:
        flag = "--save-dev" if dev else ""
        result = await _run(
            f"cd frontend && npm install {flag} {packages}", repo_dir, timeout=120
        )
        results.append(
            {
                "type": "node (frontend)",
                "command": f"cd frontend && npm install {flag} {packages}",
                **result,
            }
        )

    if not results:
        return {
            "error": "No package.json or pyproject.toml found — can't detect package manager"
        }

    return {"results": results}
