"""Sandboxed code execution and verification — runs code in isolated subprocesses.

Supports: execution, syntax checking, linting, multi-file testing, and file output.
"""

import asyncio
import shutil
import tempfile
import time
import os
import uuid
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("sandbox")

TIMEOUT_SECONDS = 60
MAX_OUTPUT_CHARS = 10000

# Track generated files for download: {download_id: {path, filename, created_at, user_id}}
_sandbox_files: dict[str, dict] = {}
EXPIRY_SECONDS = 1200  # 20 minutes


def _cleanup_expired():
    now = time.time()
    expired = [
        k for k, v in _sandbox_files.items() if now - v["created_at"] > EXPIRY_SECONDS
    ]
    for k in expired:
        path = _sandbox_files[k]["path"]
        if os.path.exists(path):
            os.remove(path)
        del _sandbox_files[k]


def get_sandbox_file(download_id: str) -> dict | None:
    """Get sandbox file info by ID — used by the REST API download endpoint."""
    _cleanup_expired()
    return _sandbox_files.get(download_id)


async def _run_subprocess(
    cmd: list[str] | str, cwd: str | None = None, shell: bool = False
) -> dict:
    """Run a subprocess with timeout and output capture."""
    try:
        if shell:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or tempfile.gettempdir(),
                env=_safe_env(),
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or tempfile.gettempdir(),
                env=_safe_env(),
            )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=TIMEOUT_SECONDS
        )
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
            "stderr": f"Timed out after {TIMEOUT_SECONDS}s",
        }
    except FileNotFoundError as e:
        return {
            "exit_code": -1,
            "passed": False,
            "stdout": "",
            "stderr": f"Command not found: {e}",
        }
    except Exception as e:
        return {"exit_code": -1, "passed": False, "stdout": "", "stderr": str(e)}


async def _write_and_run(
    code: str, cmd_prefix: list[str], suffix: str, cwd: str | None = None
) -> dict:
    """Write code to a temp file and execute it."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, dir=cwd
    ) as f:
        f.write(code)
        f.flush()
        try:
            return await _run_subprocess(cmd_prefix + [f.name], cwd=cwd)
        finally:
            os.unlink(f.name)


@mcp.tool()
async def verify_python(_user_id: int, code: str) -> dict:
    """Verify Python code WITHOUT running it — checks syntax, then lints with ruff if available.

    Use this as a fast first check before run_python. Catches syntax errors, undefined names,
    unused imports, and common bugs — all without executing the code.

    Args:
        _user_id: User ID (injected automatically)
        code: Python code to verify
    """
    issues = []

    # 1. Syntax check (always available — uses Python's built-in compiler)
    await _write_and_run(
        "import py_compile, sys\ntry:\n    py_compile.compile(sys.argv[1], doraise=True)\n    print('Syntax OK')\nexcept py_compile.PyCompileError as e:\n    print(f'SYNTAX ERROR: {e}', file=sys.stderr)\n    sys.exit(1)\n",
        ["python3"],
        suffix=".py",
    )
    # That checks the checker script, not the user code. Let me do it properly:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        target = f.name

    try:
        syntax = await _run_subprocess(["python3", "-m", "py_compile", target])
        if not syntax["passed"]:
            issues.append(
                {"check": "syntax", "passed": False, "details": syntax["stderr"]}
            )
        else:
            issues.append(
                {"check": "syntax", "passed": True, "details": "No syntax errors"}
            )

        # 2. Ruff lint (if available — catches undefined names, unused imports, etc.)
        ruff_path = shutil.which("ruff") or shutil.which(
            "ruff", path=os.path.dirname(os.sys.executable)
        )
        if ruff_path:
            ruff = await _run_subprocess(
                [ruff_path, "check", "--select", "E,F,W", "--no-fix", target]
            )
            if not ruff["passed"]:
                issues.append(
                    {
                        "check": "ruff_lint",
                        "passed": False,
                        "details": ruff["stdout"] or ruff["stderr"],
                    }
                )
            else:
                issues.append(
                    {"check": "ruff_lint", "passed": True, "details": "No lint issues"}
                )
        else:
            issues.append(
                {
                    "check": "ruff_lint",
                    "passed": True,
                    "details": "ruff not installed, skipped",
                }
            )
    finally:
        os.unlink(target)

    all_passed = all(i["passed"] for i in issues)
    return {"passed": all_passed, "checks": issues}


@mcp.tool()
async def verify_javascript(_user_id: int, code: str) -> dict:
    """Verify JavaScript code WITHOUT running it — checks syntax with Node.

    Args:
        _user_id: User ID (injected automatically)
        code: JavaScript code to verify
    """
    issues = []

    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(code)
        f.flush()
        target = f.name

    try:
        # Node --check does a syntax-only parse
        syntax = await _run_subprocess(["node", "--check", target])
        if not syntax["passed"]:
            issues.append(
                {"check": "syntax", "passed": False, "details": syntax["stderr"]}
            )
        else:
            issues.append(
                {"check": "syntax", "passed": True, "details": "No syntax errors"}
            )

        # ESLint if available
        if shutil.which("eslint"):
            lint = await _run_subprocess(
                [
                    "eslint",
                    "--no-eslintrc",
                    "--rule",
                    '{"no-undef": "error", "no-unused-vars": "warn"}',
                    target,
                ]
            )
            if not lint["passed"]:
                issues.append(
                    {
                        "check": "eslint",
                        "passed": False,
                        "details": lint["stdout"] or lint["stderr"],
                    }
                )
            else:
                issues.append(
                    {"check": "eslint", "passed": True, "details": "No lint issues"}
                )
    finally:
        os.unlink(target)

    all_passed = all(i["passed"] for i in issues)
    return {"passed": all_passed, "checks": issues}


@mcp.tool()
async def run_python(_user_id: int, code: str, test_code: str = "") -> dict:
    """Execute Python code in a sandboxed subprocess. Optionally run test code after the main code.

    Use this to test generated code before pushing it to GitHub.
    The test_code runs in the same file after the main code, so it can import/use anything defined in code.

    Args:
        _user_id: User ID (injected automatically)
        code: Python code to execute
        test_code: Optional test code (e.g., assertions, unittest) to run after the main code
    """
    full_code = code
    if test_code:
        full_code += "\n\n# === Tests ===\n" + test_code

    return await _write_and_run(full_code, ["python3"], suffix=".py")


@mcp.tool()
async def run_javascript(_user_id: int, code: str, test_code: str = "") -> dict:
    """Execute JavaScript/Node.js code in a sandboxed subprocess. Optionally run test code after the main code.

    Use this to test generated code before pushing it to GitHub.

    Args:
        _user_id: User ID (injected automatically)
        code: JavaScript code to execute
        test_code: Optional test code to run after the main code
    """
    full_code = code
    if test_code:
        full_code += "\n\n// === Tests ===\n" + test_code

    return await _write_and_run(full_code, ["node"], suffix=".js")


@mcp.tool()
async def run_shell(_user_id: int, command: str) -> dict:
    """Execute a shell command in a sandboxed subprocess.

    Useful for running test suites (e.g., pytest, npm test) or checking if dependencies are available.

    Args:
        _user_id: User ID (injected automatically)
        command: Shell command to execute
    """
    return await _run_subprocess(command, shell=True)


@mcp.tool()
async def run_multi_file_test(_user_id: int, files: dict, entry_command: str) -> dict:
    """Write multiple files to a temp directory and run a command. Perfect for testing a multi-file project.

    Args:
        _user_id: User ID (injected automatically)
        files: Dict of {filename: content} — files will be written to a temp directory
        entry_command: Command to run (e.g., "python3 main.py" or "pytest test_main.py")
    """
    with tempfile.TemporaryDirectory(prefix="openpa_sandbox_") as tmpdir:
        for filename, content in files.items():
            filepath = Path(tmpdir) / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)

        result = await _run_subprocess(entry_command, cwd=tmpdir, shell=True)
        result["files_written"] = list(files.keys())
        return result


@mcp.tool()
async def run_and_export(
    _user_id: int, code: str, output_filename: str, language: str = "python"
) -> dict:
    """Run code that produces an output file (CSV, JSON, TXT, etc.) and return a download link.

    The code should write its output to the filename specified by output_filename in the current directory.
    For example, if output_filename is "medalists.csv", the code should write to "medalists.csv".

    Args:
        _user_id: User ID (injected automatically)
        code: Code to execute that generates the output file
        output_filename: The filename the code will write (e.g., "results.csv", "data.json")
        language: "python" or "javascript"
    """
    _cleanup_expired()

    with tempfile.TemporaryDirectory(prefix="openpa_export_") as tmpdir:
        # Write the code
        suffix = ".py" if language == "python" else ".js"
        cmd = ["python3"] if language == "python" else ["node"]
        code_path = Path(tmpdir) / f"script{suffix}"
        code_path.write_text(code)

        result = await _run_subprocess(cmd + [str(code_path)], cwd=tmpdir)

        output_path = Path(tmpdir) / output_filename
        if not output_path.exists():
            result["file_error"] = (
                f"Code ran but did not create '{output_filename}'. Check your code writes to this exact filename."
            )
            return result

        # Move file to a persistent location for download
        download_id = str(uuid.uuid4())[:8]
        persist_dir = Path("/tmp/openpa_sandbox_exports")
        persist_dir.mkdir(exist_ok=True)
        persist_path = persist_dir / f"{download_id}_{output_filename}"
        shutil.copy2(str(output_path), str(persist_path))

        _sandbox_files[download_id] = {
            "path": str(persist_path),
            "filename": output_filename,
            "created_at": time.time(),
            "user_id": _user_id,
        }

        # Include a preview of the file content
        preview = ""
        try:
            preview = persist_path.read_text(errors="replace")[:2000]
        except Exception:
            pass

        result["download_id"] = download_id
        result["download_url"] = f"/api/download/sandbox/{download_id}"
        result["filename"] = output_filename
        result["preview"] = preview
        result["expires_in"] = "20 minutes"
        return result


def _safe_env() -> dict:
    """Create a restricted environment for subprocess execution."""
    env = os.environ.copy()
    for key in list(env.keys()):
        if any(
            s in key.upper()
            for s in ["SECRET", "TOKEN", "PASSWORD", "API_KEY", "CREDENTIAL"]
        ):
            del env[key]
    env["HOME"] = tempfile.gettempdir()
    return env
