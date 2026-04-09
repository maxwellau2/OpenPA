"""GitHub tools using the GitHub REST API. Credentials per-user from DB."""

import base64

import httpx
from fastmcp import FastMCP

from tools.credentials import get_creds

mcp = FastMCP("github")
API_BASE = "https://api.github.com"


async def _headers(user_id: int) -> dict:
    creds = await get_creds(user_id, "github")
    return {
        "Authorization": f"Bearer {creds['token']}",
        "Accept": "application/vnd.github.v3+json",
    }


async def _default_branch(user_id: int, repo: str) -> str:
    """Get the default branch for a repo (main, master, etc.)."""
    headers = await _headers(user_id)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(f"{API_BASE}/repos/{repo}", headers=headers)
        resp.raise_for_status()
        return resp.json().get("default_branch", "main")


@mcp.tool()
async def create_repo(
    _user_id: int, name: str, description: str = "", private: bool = False, auto_init: bool = True
) -> dict:
    """Create a new GitHub repository for the authenticated user.

    Args:
        _user_id: User ID (injected automatically)
        name: Repository name (e.g. "graph-algos-py")
        description: Short description of the repo
        private: Whether the repo should be private
        auto_init: Initialize with a README (set True so you can immediately push files)
    """
    headers = await _headers(_user_id)
    payload = {
        "name": name,
        "description": description,
        "private": private,
        "auto_init": auto_init,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API_BASE}/user/repos", headers=headers, json=payload)
        resp.raise_for_status()
        repo = resp.json()
    return {
        "full_name": repo["full_name"],
        "url": repo["html_url"],
        "clone_url": repo["clone_url"],
        "private": repo["private"],
        "default_branch": repo.get("default_branch", "main"),
    }


@mcp.tool()
async def list_repos(_user_id: int, limit: int = 20) -> dict:
    """List the authenticated user's GitHub repositories. Call this first to discover repo names before using other GitHub tools.

    Args:
        _user_id: User ID (injected automatically)
        limit: Max repos to return (sorted by most recently pushed)
    """
    headers = await _headers(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/user/repos",
            headers=headers,
            params={"sort": "pushed", "per_page": limit, "affiliation": "owner,collaborator,organization_member"},
        )
        resp.raise_for_status()
        repos = resp.json()
    return {"repos": [
        {
            "full_name": r["full_name"],
            "description": (r.get("description") or "")[:100],
            "private": r["private"],
            "open_issues": r["open_issues_count"],
            "pushed_at": r["pushed_at"],
        }
        for r in repos
    ]}


@mcp.tool()
async def list_prs(_user_id: int, repo: str = "", state: str = "open") -> dict:
    """List pull requests for a repository. If no repo is given, lists PRs across your most recent repos.

    Args:
        _user_id: User ID (injected automatically)
        repo: Repository in owner/repo format (optional — if empty, checks recent repos)
        state: PR state: open, closed, all
    """
    headers = await _headers(_user_id)

    # If no repo specified, find repos with open issues/PRs
    if not repo:
        repos_data = await list_repos(_user_id, limit=10)
        all_prs = []
        async with httpx.AsyncClient() as client:
            for r in repos_data["repos"][:5]:  # Check top 5 most recent repos
                try:
                    resp = await client.get(
                        f"{API_BASE}/repos/{r['full_name']}/pulls",
                        headers=headers,
                        params={"state": state, "per_page": 5},
                    )
                    resp.raise_for_status()
                    for pr in resp.json():
                        all_prs.append({
                            "repo": r["full_name"],
                            "number": pr["number"],
                            "title": pr["title"],
                            "author": pr["user"]["login"],
                            "url": pr["html_url"],
                            "state": pr["state"],
                            "created_at": pr["created_at"],
                        })
                except Exception:
                    continue
        return {"pull_requests": all_prs}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/repos/{repo}/pulls",
            headers=headers,
            params={"state": state, "per_page": 20},
        )
        resp.raise_for_status()
        prs = resp.json()
    return {"pull_requests": [
        {
            "repo": repo,
            "number": pr["number"],
            "title": pr["title"],
            "author": pr["user"]["login"],
            "url": pr["html_url"],
            "state": pr["state"],
            "created_at": pr["created_at"],
        }
        for pr in prs
    ]}


@mcp.tool()
async def get_pr_diff(_user_id: int, repo: str, pr_number: int) -> dict:
    """Get the diff/changes for a pull request.

    Args:
        _user_id: User ID (injected automatically)
        repo: Repository in owner/repo format
        pr_number: PR number
    """
    creds = await get_creds(_user_id, "github")
    diff_headers = {
        "Authorization": f"Bearer {creds['token']}",
        "Accept": "application/vnd.github.v3.diff",
    }
    json_headers = await _headers(_user_id)

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/repos/{repo}/pulls/{pr_number}", headers=diff_headers)
        resp.raise_for_status()
        diff = resp.text

        meta_resp = await client.get(f"{API_BASE}/repos/{repo}/pulls/{pr_number}", headers=json_headers)
        meta_resp.raise_for_status()
        meta = meta_resp.json()

    return {
        "title": meta["title"],
        "body": meta.get("body", ""),
        "author": meta["user"]["login"],
        "diff": diff[:10000],
        "files_changed": meta.get("changed_files", 0),
        "additions": meta.get("additions", 0),
        "deletions": meta.get("deletions", 0),
    }


@mcp.tool()
async def create_issue(_user_id: int, repo: str, title: str, body: str, labels: str = "") -> dict:
    """Create a new GitHub issue.

    Args:
        _user_id: User ID (injected automatically)
        repo: Repository in owner/repo format
        title: Issue title
        body: Issue body (markdown)
        labels: Comma-separated labels
    """
    headers = await _headers(_user_id)
    label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else []
    payload = {"title": title, "body": body}
    if label_list:
        payload["labels"] = label_list

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API_BASE}/repos/{repo}/issues", headers=headers, json=payload)
        resp.raise_for_status()
        issue = resp.json()
    return {"url": issue["html_url"], "number": issue["number"]}


@mcp.tool()
async def create_pr(_user_id: int, repo: str, title: str, body: str, head: str, base: str = "") -> dict:
    """Create a new pull request. Auto-detects the default branch if base is not specified.

    Args:
        _user_id: User ID (injected automatically)
        repo: Repository in owner/repo format
        title: PR title
        body: PR description
        head: Branch with changes
        base: Branch to merge into (auto-detected if empty — usually 'main' or 'master')
    """
    headers = await _headers(_user_id)

    # Auto-detect default branch if not specified
    if not base:
        base = await _default_branch(_user_id, repo)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/repos/{repo}/pulls",
            headers=headers,
            json={"title": title, "body": body, "head": head, "base": base},
        )
        if resp.status_code >= 400:
            error_body = resp.json()
            errors = error_body.get("errors", [])
            # Extract all useful fields from error objects
            error_details = []
            for e in errors:
                parts = [v for k, v in e.items() if isinstance(v, str) and v]
                error_details.append("; ".join(parts) if parts else str(e))
            raise RuntimeError(
                f"GitHub PR creation failed ({resp.status_code}): {error_body.get('message', 'Unknown error')}. "
                + (f"Details: {' | '.join(error_details)}" if error_details else f"Raw: {error_body}")
            )
        pr = resp.json()
    return {"url": pr["html_url"], "number": pr["number"]}


@mcp.tool()
async def list_notifications(_user_id: int) -> dict:
    """List GitHub notifications.

    Args:
        _user_id: User ID (injected automatically)
    """
    headers = await _headers(_user_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/notifications", headers=headers, params={"per_page": 20})
        resp.raise_for_status()
        notifs = resp.json()
    return {"notifications": [
        {
            "reason": n["reason"],
            "title": n["subject"]["title"],
            "type": n["subject"]["type"],
            "url": n["subject"].get("url", ""),
            "updated_at": n["updated_at"],
        }
        for n in notifs
    ]}


@mcp.tool()
async def create_branch(_user_id: int, repo: str, branch: str, from_branch: str = "") -> dict:
    """Create a new branch in a repository. Use this before pushing files for a new feature.

    Args:
        _user_id: User ID (injected automatically)
        repo: Repository in owner/repo format
        branch: Name of the new branch to create
        from_branch: Branch to base the new branch on (auto-detects default if empty)
    """
    if not from_branch:
        from_branch = await _default_branch(_user_id, repo)
    headers = await _headers(_user_id)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Get the SHA of the source branch
        resp = await client.get(
            f"{API_BASE}/repos/{repo}/git/ref/heads/{from_branch}",
            headers=headers,
        )
        resp.raise_for_status()
        sha = resp.json()["object"]["sha"]

        # Create the new branch (or confirm it already exists)
        resp = await client.post(
            f"{API_BASE}/repos/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if resp.status_code == 422:
            # Branch already exists — that's fine, just return it
            return {"branch": branch, "sha": sha, "based_on": from_branch, "note": "branch already existed"}
        resp.raise_for_status()
    return {"branch": branch, "sha": sha, "based_on": from_branch}


@mcp.tool()
async def list_files(_user_id: int, repo: str, path: str = "", branch: str = "") -> dict:
    """List files and directories in a repository path. Use this to explore repo structure.

    Args:
        _user_id: User ID (injected automatically)
        repo: Repository in owner/repo format
        path: Directory path (empty string for root)
        branch: Branch to list from (auto-detects default if empty)
    """
    if not branch:
        branch = await _default_branch(_user_id, repo)
    headers = await _headers(_user_id)
    params = {"ref": branch}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(
            f"{API_BASE}/repos/{repo}/contents/{path}",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

    # contents endpoint returns a list for directories, a dict for files
    if isinstance(data, dict):
        return {"type": "file", "name": data["name"], "size": data.get("size", 0)}

    return {"files": [
        {
            "name": item["name"],
            "type": item["type"],  # "file" or "dir"
            "path": item["path"],
            "size": item.get("size", 0),
        }
        for item in data
    ]}


@mcp.tool()
async def get_file(_user_id: int, repo: str, path: str, branch: str = "") -> dict:
    """Read the contents of a file in a repository. Use this to understand existing code before modifying it.

    Args:
        _user_id: User ID (injected automatically)
        repo: Repository in owner/repo format
        path: File path in the repo
        branch: Branch to read from (auto-detects default if empty)
    """
    if not branch:
        branch = await _default_branch(_user_id, repo)
    headers = await _headers(_user_id)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(
            f"{API_BASE}/repos/{repo}/contents/{path}",
            headers=headers,
            params={"ref": branch},
        )
        resp.raise_for_status()
        data = resp.json()

    content = ""
    if data.get("content"):
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    return {
        "path": data["path"],
        "size": data.get("size", 0),
        "sha": data["sha"],
        "content": content[:50000],  # Cap at 50k chars
    }


@mcp.tool()
async def push_file(_user_id: int, repo: str, path: str, content: str, message: str, branch: str) -> dict:
    """Create or update a file in a GitHub repository.

    Args:
        _user_id: User ID (injected automatically)
        repo: Repository in owner/repo format
        path: File path in the repo
        content: File content
        message: Commit message
        branch: Branch to push to
    """
    headers = await _headers(_user_id)
    encoded = base64.b64encode(content.encode()).decode()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        existing = await client.get(
            f"{API_BASE}/repos/{repo}/contents/{path}",
            headers=headers,
            params={"ref": branch},
        )
        payload = {"message": message, "content": encoded, "branch": branch}
        if existing.status_code == 200:
            payload["sha"] = existing.json()["sha"]

        resp = await client.put(f"{API_BASE}/repos/{repo}/contents/{path}", headers=headers, json=payload)
        resp.raise_for_status()
        result = resp.json()

    return {"sha": result["commit"]["sha"], "url": result["content"]["html_url"]}
