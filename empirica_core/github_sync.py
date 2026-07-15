"""Mirror a client dashboard's ``committed_actuals.json`` to GitHub.

Streamlit Community Cloud has an ephemeral filesystem, so anything a client
commits through the UI is lost on redeploy unless it is pushed back to the
repo. This module PUTs the committed file to GitHub via the Contents API.

Uses only the standard library — no PyGithub or requests dependency.

Token and repo are read from ``st.secrets`` (falling back to environment
variables), so nothing is hard-coded per client. Each dashboard's
``BaseDataStore`` subclass passes its ``repo_file_path`` and ``default_repo``.

Extracted verbatim from the CNS / Mighty Pilates ``github_sync.py`` modules
and parameterized so all three dashboards share one implementation.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

DEFAULT_BRANCH = "main"


def _read_secret(key: str) -> Optional[str]:
    """Read ``key`` from Streamlit secrets, falling back to ``KEY`` in env."""
    try:
        import streamlit as st

        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key.upper())


def sync_enabled() -> bool:
    """True when a GitHub token is configured (secrets or env)."""
    return bool(_read_secret("github_token"))


def push_committed_file(
    local_path: Path,
    commit_message: str,
    *,
    repo_file_path: str,
    default_repo: str,
    default_branch: str = DEFAULT_BRANCH,
) -> dict:
    """Push ``local_path`` to ``repo_file_path`` in the client repo.

    ``default_repo`` (``owner/name``) and ``default_branch`` may be overridden
    at runtime via the ``github_repo`` / ``github_branch`` secrets. Returns a
    status dict ``{ok, message, sha, url}`` — never raises.
    """
    token = _read_secret("github_token")
    if not token:
        return {"ok": False, "message": "no token configured", "sha": None, "url": None}

    repo = _read_secret("github_repo") or default_repo
    branch = _read_secret("github_branch") or default_branch
    api = f"https://api.github.com/repos/{repo}/contents/{repo_file_path}"

    try:
        content_bytes = Path(local_path).read_bytes()
    except FileNotFoundError:
        return {"ok": False, "message": f"local file not found: {local_path}",
                "sha": None, "url": None}

    existing_sha = _get_existing_sha(api, branch, token)

    payload = {
        "message": commit_message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch": branch,
    }
    if existing_sha:
        payload["sha"] = existing_sha

    req = urllib.request.Request(
        api,
        data=json.dumps(payload).encode("utf-8"),
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"ok": False,
                "message": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}",
                "sha": None, "url": None}
    except urllib.error.URLError as e:
        return {"ok": False, "message": f"network error: {e.reason}",
                "sha": None, "url": None}

    return {
        "ok": True,
        "message": "pushed to GitHub",
        "sha": body.get("content", {}).get("sha"),
        "url": body.get("commit", {}).get("html_url"),
    }


def _get_existing_sha(api_url: str, branch: str, token: str) -> Optional[str]:
    """Get the current blob SHA so we can update rather than create."""
    req = urllib.request.Request(
        f"{api_url}?ref={branch}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


__all__ = ["sync_enabled", "push_committed_file", "DEFAULT_BRANCH"]
