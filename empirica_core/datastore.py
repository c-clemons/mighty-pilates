"""Shared base class for Empirica CFO dashboard data stores.

Two-layer singleton persistence, backed by a durable JSON store (GCS on Cloud
Run, local files in dev — see ``empirica_core.storage.JsonStore``):

* ``committed_actuals.json`` — locked state (actuals, mappings).
* ``user_overrides.json`` — soft state (assumptions, scenarios).
* ``scenarios/<name>.json`` — saved scenarios.

State is **shared** across all users of a client's portal and **durable** across
redeploys. Writes are **gated**: only sessions flagged writable (admin /
management, set by ``run_app``) can persist changes — everyone else is read-only,
which also avoids concurrent-write conflicts.

**Read-through seeding:** a ``committed_actuals.json`` / ``baseline.json`` shipped
in the repo is the initial value until the first write lands in GCS, so no
existing data is lost when a client first moves onto the durable store.

A subclass supplies only what differs per client::

    class DataStore(BaseDataStore):
        DATA_DIR = Path(__file__).parent / "data"
        APP_KEY = "mighty"                       # GCS state namespace
        COMMITTED_KEYS = ("metadata", "pl", ...)
        MERGE_LISTS = True
        def _load_baseline(self): ...            # in-code dict or baseline.json
        def _load_actuals(self): ...
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from empirica_core.storage import JsonStore


def _now_iso() -> str:
    return datetime.now().isoformat()


class BaseDataStore:
    # --- subclass configuration -------------------------------------------
    DATA_DIR: Optional[Path] = None            # REQUIRED: local dir (seed + dev)
    APP_KEY: Optional[str] = None              # GCS state namespace (e.g. "cns")
    STATE_BUCKET: str = "empirica-portals-state"  # durable store bucket
    COMMITTED_KEYS: tuple = ()                  # keys that belong in committed file
    MERGE_LISTS: bool = False                   # concat baseline+override lists?
    # Deprecated (GCS replaces GitHub sync); kept so subclass defs don't break:
    GITHUB_REPO: Optional[str] = None
    GITHUB_REPO_FILE_PATH: Optional[str] = None

    _instance: Optional["BaseDataStore"] = None

    # --- singleton --------------------------------------------------------
    @classmethod
    def get(cls) -> "BaseDataStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def __init__(self) -> None:
        if self.DATA_DIR is None:
            raise NotImplementedError(
                f"{type(self).__name__} must set DATA_DIR to its data directory."
            )
        self.data_dir = Path(self.DATA_DIR)
        # Durable store: GCS on Cloud Run, local files otherwise. The bundled
        # data_dir is the read-through seed either way.
        self._store = JsonStore(
            app_key=self.APP_KEY or type(self).__name__.lower(),
            bucket=self.STATE_BUCKET if os.environ.get("K_SERVICE") else None,
            local_dir=self.data_dir,
        )

        self.baseline: dict = {}
        self.overrides: dict = {}
        self.committed: dict = {}
        self.merged: dict = {}
        self.actuals: dict = {}
        self._loaded = False
        self.load()

    # --- write gate -------------------------------------------------------
    def _can_write(self) -> bool:
        """True if the current session may persist changes.

        ``run_app`` sets ``st.session_state['_empirica_can_write']`` from the
        user's role (admin/management). Outside Streamlit (tests/CLI) writing
        is allowed.
        """
        from empirica_core.storage import session_can_write
        return session_can_write()

    # --- durable I/O ------------------------------------------------------
    def _read(self, key: str) -> dict:
        return self._store.read(key) or {}

    def _write(self, key: str, data: dict) -> bool:
        return self._store.write(key, data)

    # --- load / merge -----------------------------------------------------
    def load(self) -> None:
        self.baseline = self._load_baseline()
        self.overrides = self._read("user_overrides.json")
        self.committed = self._read("committed_actuals.json")
        self._migrate_committed_from_overrides()
        self.merged = self._deep_merge(self.baseline, self.overrides)
        self._load_actuals()
        self._loaded = True

    def reload(self) -> None:
        self._loaded = False
        self.load()

    # --- hooks (override in subclass) -------------------------------------
    def _load_baseline(self) -> dict:
        """Merge-base data. Default reads the shipped ``baseline.json``."""
        return self._read("baseline.json")

    def _load_actuals(self) -> None:
        return None

    # --- migration --------------------------------------------------------
    def _migrate_committed_from_overrides(self) -> None:
        moved = False
        for key in self.COMMITTED_KEYS:
            if key in self.overrides:
                self.committed.setdefault(key, self.overrides[key])
                del self.overrides[key]
                moved = True
        if moved and self._can_write():
            self._write("committed_actuals.json", self.committed)
            self._write("user_overrides.json", self.overrides)

    # --- scenarios (writer-only mutations) --------------------------------
    def save_scenario(self, name: str) -> None:
        if not self._can_write():
            return
        data = copy.deepcopy(self.overrides)
        data["_scenario_name"] = name
        data["_saved_at"] = _now_iso()
        self._write(f"scenarios/{name}.json", data)

    def load_scenario(self, name: str) -> None:
        # Loading replaces the shared overrides, so it's a writer action.
        if not self._can_write():
            return
        data = self._store.read(f"scenarios/{name}.json")
        if data is None:
            raise FileNotFoundError(f"Scenario '{name}' not found")
        self.overrides = data
        self.merged = self._deep_merge(self.baseline, self.overrides)
        self.save_overrides()

    def list_scenarios(self) -> list:
        out = []
        for key in self._store.list("scenarios"):
            data = self._store.read(key) or {}
            name = key.split("/")[-1]
            if name.endswith(".json"):
                name = name[:-5]
            out.append({"name": name, "saved_at": data.get("_saved_at", "Unknown")})
        return out

    def delete_scenario(self, name: str) -> None:
        if not self._can_write():
            return
        self._store.delete(f"scenarios/{name}.json")

    # --- persistence (writer-only) ----------------------------------------
    def save_overrides(self) -> None:
        if not self._can_write():
            return
        self.overrides["_last_updated"] = _now_iso()
        self._write("user_overrides.json", self.overrides)

    def save_committed(self, commit_message: Optional[str] = None) -> dict:
        """Persist the committed file to the durable store.

        Returns ``{ok, message, sha, url}`` (sha/url kept for call-site
        compatibility; always None now that GCS, not GitHub, is the store).
        """
        if not self._can_write():
            return {"ok": False, "message": "read-only (needs admin/management)",
                    "sha": None, "url": None}
        self.committed["_last_updated"] = _now_iso()
        ok = self._write("committed_actuals.json", self.committed)
        return {"ok": ok,
                "message": "saved to durable store" if ok else "save failed",
                "sha": None, "url": None}

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
