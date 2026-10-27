"""Canonical locations for the shared, gitignored state.

WHY THIS EXISTS
---------------
`data/` and `dashboard/data/` are gitignored shared state, not per-branch
source. But every module used to resolve them as `Path(__file__).parent.parent`,
which is the *worktree* root — so each worktree got its own private copy.

The portal (`~/mighty-portal-v2`) reads `~/mighty-pilates/data/financials`, i.e.
the MAIN checkout. On 2026-10-27 that directory was still stale at June while a
worktree held September: the portal would have built its debt register off June
balances without complaining, because nothing checks.

So the actuals pipeline now writes to ONE canonical place that every worktree
and the portal agree on:

  1. `$MIGHTY_FINANCIALS` if set — the same variable the portal's extractors
     already honour, so overriding one overrides both.
  2. otherwise the main checkout, found via `git rev-parse --git-common-dir`
     (from a worktree that points at `<main>/.git`).
  3. otherwise this repo root, for a plain clone with no worktrees.
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def main_checkout() -> Path:
    """The main working tree, even when called from a linked worktree."""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        if common:
            root = (_REPO_ROOT / common).resolve().parent \
                if not Path(common).is_absolute() else Path(common).resolve().parent
            if (root / "run.py").exists():
                return root
    except (subprocess.CalledProcessError, OSError):
        pass
    return _REPO_ROOT


@lru_cache(maxsize=1)
def financials_dir() -> Path:
    """Where the accountant's imported CSVs live. Shared with the portal."""
    env = os.environ.get("MIGHTY_FINANCIALS")
    if env:
        return Path(env).expanduser().resolve()
    return main_checkout() / "data" / "financials"


# NOTE: there is deliberately no dashboard_data_dir() here.
# `dashboard/data/committed_actuals.json` is git-TRACKED and committed on the
# branch doing the work, so it must stay local to the worktree. Redirecting it
# at the main checkout would write a tracked file into whatever branch that
# checkout happens to have out. The portal reads the main checkout's copy, so
# the way to keep the portal current is to MERGE, not to redirect writes.


def describe() -> str:
    """One line for the CLI banners, so the target is never a guess."""
    where = "main checkout"
    if os.environ.get("MIGHTY_FINANCIALS"):
        where = "$MIGHTY_FINANCIALS"
    elif main_checkout() == _REPO_ROOT:
        where = "this checkout"
    return f"{financials_dir()}  ({where})"
