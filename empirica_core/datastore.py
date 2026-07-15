"""Shared base class for Empirica CFO dashboard data stores.

Generalizes the two-file singleton persistence pattern used by the CNS,
Mighty Pilates, and Alma Mater dashboards:

* ``committed_actuals.json`` — locked state (actuals, mappings). Git-tracked
  and mirrored to GitHub on explicit commit so it survives Streamlit Cloud
  redeploys.
* ``user_overrides.json`` — soft state (assumptions, scenarios). Ephemeral.

A subclass supplies only what differs per client:

    class DataStore(BaseDataStore):
        DATA_DIR = Path(__file__).parent / "data"
        COMMITTED_KEYS = ("metadata", "pl", "bs", ...)
        MERGE_LISTS = True                       # concat baseline+override lists
        GITHUB_REPO = "c-clemons/mighty-pilates"
        GITHUB_REPO_FILE_PATH = "dashboard/data/committed_actuals.json"

        def _load_baseline(self):                # JSON file (default) or in-code dict
            return self._load_json(self.data_dir / "baseline.json")

        def _load_actuals(self):                 # client-specific hydration
            ...

Everything else — the singleton ``get()``, ``load()``, override→committed
migration, deep merge, scenarios, ``save_overrides``/``save_committed`` (with
GitHub push), and the JSON helpers — is inherited unchanged.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now().isoformat()


class BaseDataStore:
    # --- subclass configuration -------------------------------------------
    DATA_DIR: Optional[Path] = None            # REQUIRED: where the JSON lives
    COMMITTED_KEYS: tuple = ()                  # keys that belong in committed file
    MERGE_LISTS: bool = False                   # concat baseline+override lists?
    GITHUB_REPO: Optional[str] = None           # "owner/name" for sync (optional)
    GITHUB_REPO_FILE_PATH: Optional[str] = None  # path to committed file in repo

    _instance: Optional["BaseDataStore"] = None

    # --- singleton --------------------------------------------------------
    @classmethod
    def get(cls) -> "BaseDataStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the cached singleton (used by tests and hot-reload)."""
        cls._instance = None

    def __init__(self) -> None:
        if self.DATA_DIR is None:
            raise NotImplementedError(
                f"{type(self).__name__} must set DATA_DIR to its data directory."
            )
        self.data_dir = Path(self.DATA_DIR)
        self.overrides_path = self.data_dir / "user_overrides.json"
        self.committed_path = self.data_dir / "committed_actuals.json"

        self.baseline: dict = {}
        self.overrides: dict = {}
        self.committed: dict = {}
        self.merged: dict = {}
        self.actuals: dict = {}
        self._loaded = False
        # Auto-load so a freshly recreated singleton (Streamlit hot-reload)
        # never starts empty.
        self.load()

    # --- load / merge -----------------------------------------------------
    def load(self) -> None:
        self.baseline = self._load_baseline()
        self.overrides = self._load_json(self.overrides_path)
        self.committed = self._load_json(self.committed_path)
        self._migrate_committed_from_overrides()
        self.merged = self._deep_merge(self.baseline, self.overrides)
        self._load_actuals()
        self._loaded = True

    def reload(self) -> None:
        self._loaded = False
        self.load()

    # --- hooks (override in subclass) -------------------------------------
    def _load_baseline(self) -> dict:
        """Return the merge-base data.

        Default reads ``data_dir/baseline.json`` (Mighty style). Clients that
        keep their baseline in code (CNS/Alma Mater) override this to return
        ``copy.deepcopy(DEFAULT_ASSUMPTIONS)``.
        """
        return self._load_json(self.data_dir / "baseline.json")

    def _load_actuals(self) -> None:
        """Hydrate ``self.actuals`` from committed data. Default: no-op."""
        return None

    # --- migration --------------------------------------------------------
    def _migrate_committed_from_overrides(self) -> None:
        """Pull committed keys out of the soft file. Idempotent."""
        moved = False
        for key in self.COMMITTED_KEYS:
            if key in self.overrides:
                self.committed.setdefault(key, self.overrides[key])
                del self.overrides[key]
                moved = True
        if moved:
            self._save_json(self.committed_path, self.committed)
            self._save_json(self.overrides_path, self.overrides)

    # --- scenarios --------------------------------------------------------
    def save_scenario(self, name: str) -> None:
        scenario_dir = self.data_dir / "scenarios"
        scenario_dir.mkdir(parents=True, exist_ok=True)
        data = copy.deepcopy(self.overrides)
        data["_scenario_name"] = name
        data["_saved_at"] = _now_iso()
        self._save_json(scenario_dir / f"{name}.json", data)

    def load_scenario(self, name: str) -> None:
        path = self.data_dir / "scenarios" / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Scenario '{name}' not found")
        self.overrides = self._load_json(path)
        self.merged = self._deep_merge(self.baseline, self.overrides)
        self.save_overrides()

    def list_scenarios(self) -> list:
        scenario_dir = self.data_dir / "scenarios"
        if not scenario_dir.exists():
            return []
        out = []
        for f in sorted(scenario_dir.glob("*.json")):
            data = self._load_json(f)
            out.append({"name": f.stem, "saved_at": data.get("_saved_at", "Unknown")})
        return out

    def delete_scenario(self, name: str) -> None:
        path = self.data_dir / "scenarios" / f"{name}.json"
        if path.exists():
            path.unlink()

    # --- persistence ------------------------------------------------------
    def save_overrides(self) -> None:
        self.overrides["_last_updated"] = _now_iso()
        self._save_json(self.overrides_path, self.overrides)

    def save_committed(self, commit_message: Optional[str] = None) -> dict:
        """Write the committed file and mirror it to GitHub.

        Returns a status dict ``{ok, message, sha, url}``. GitHub push is a
        no-op (``ok=False``) when the repo isn't configured or no token is set.
        """
        self.committed["_last_updated"] = _now_iso()
        self._save_json(self.committed_path, self.committed)

        if not (self.GITHUB_REPO and self.GITHUB_REPO_FILE_PATH):
            return {"ok": False, "message": "github sync not configured",
                    "sha": None, "url": None}
        try:
            from empirica_core import github_sync
        except Exception:
            return {"ok": False, "message": "github_sync import failed",
                    "sha": None, "url": None}
        if not github_sync.sync_enabled():
            return {"ok": False, "message": "no token configured",
                    "sha": None, "url": None}
        return github_sync.push_committed_file(
            self.committed_path,
            commit_message or f"update committed actuals ({self.committed['_last_updated']})",
            repo_file_path=self.GITHUB_REPO_FILE_PATH,
            default_repo=self.GITHUB_REPO,
        )

    # --- static / class helpers -------------------------------------------
    @staticmethod
    def _load_json(path: Path) -> dict:
        path = Path(path)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    @staticmethod
    def _save_json(path: Path, data: dict) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    @classmethod
    def _deep_merge(cls, base: dict, override: dict) -> dict:
        """Recursively merge ``override`` into ``base``. Override wins.

        Keys starting with ``_`` are skipped (metadata). When ``MERGE_LISTS``
        is set, list values are concatenated (baseline + override) rather than
        replaced — used by Mighty for ``loans``.
        """
        result = copy.deepcopy(base)
        for key, val in override.items():
            if key.startswith("_"):
                continue
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = cls._deep_merge(result[key], val)
            elif (cls.MERGE_LISTS and key in result
                  and isinstance(result[key], list) and isinstance(val, list)):
                result[key] = result[key] + val
            else:
                result[key] = copy.deepcopy(val)
        return result


__all__ = ["BaseDataStore"]
