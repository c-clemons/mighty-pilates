"""Durable JSON storage — GCS-backed with a local-file fallback.

One logical store per client app. Keys are relative names like
``"user_overrides.json"`` or ``"scenarios/base.json"``. On Cloud Run the objects
live at ``gs://<bucket>/state/<app>/<key>``; with no bucket (local dev) they fall
back to ``<local_dir>/<key>``.

**Read-through seeding:** :meth:`read` checks GCS first, then the local dir. So a
file bundled in the repo (e.g. a seed ``committed_actuals.json``) is the initial
value until the first write lands in GCS — existing shipped data is never lost
when a client first goes live on the durable store.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional


def session_can_write() -> bool:
    """True if the current session may persist changes.

    ``run_app`` (or a client's ``main``) sets
    ``st.session_state['_empirica_can_write']`` from the user's role
    (admin/management). Outside an active Streamlit run — CLI, pipeline, tests —
    writing is allowed.
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is None:
            return True
        import streamlit as st
        return bool(st.session_state.get("_empirica_can_write", False))
    except Exception:
        return True


class JsonStore:
    def __init__(self, app_key: str, *, bucket: Optional[str] = None,
                 local_dir: Optional[Path] = None) -> None:
        self.app_key = app_key
        self.bucket = bucket
        self.local_dir = Path(local_dir) if local_dir else None
        self._last: dict = {}  # key -> last-written payload, to skip redundant writes

    # --- internals ---------------------------------------------------------
    def _obj(self, key: str) -> str:
        return f"state/{self.app_key}/{key}"

    def _blob(self, key: str):
        from google.cloud import storage
        return storage.Client().bucket(self.bucket).blob(self._obj(key))

    # --- API ---------------------------------------------------------------
    def read(self, key: str) -> Optional[dict]:
        """Return the parsed JSON at ``key`` (GCS → local seed → None)."""
        if self.bucket:
            try:
                b = self._blob(key)
                if b.exists():
                    return json.loads(b.download_as_text())
            except Exception:
                pass
        if self.local_dir:
            p = self.local_dir / key
            if p.exists():
                return json.loads(p.read_text())
        return None

    def write(self, key: str, data) -> bool:
        """Persist ``data`` as JSON at ``key``. GCS when configured, else local.

        Skips the write if the payload is byte-identical to the last one written
        this process (so per-render auto-saves don't thrash GCS).
        """
        payload = json.dumps(data, indent=2, default=str)
        if self._last.get(key) == payload:
            return True
        if self.bucket:
            try:
                self._blob(key).upload_from_string(
                    payload, content_type="application/json")
                self._last[key] = payload
                return True
            except Exception:
                pass
        if self.local_dir:
            p = self.local_dir / key
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(payload)
            self._last[key] = payload
            return True
        return False

    def delete(self, key: str) -> None:
        if self.bucket:
            try:
                self._blob(key).delete()
            except Exception:
                pass
        if self.local_dir:
            p = self.local_dir / key
            if p.exists():
                p.unlink()

    def list(self, prefix: str) -> List[str]:
        """List keys under ``prefix`` (e.g. ``"scenarios/"``), from both backends."""
        prefix = prefix if prefix.endswith("/") else prefix + "/"
        keys = set()
        if self.bucket:
            try:
                from google.cloud import storage
                base = self._obj("")
                full = self._obj(prefix)
                for b in storage.Client().list_blobs(self.bucket, prefix=full):
                    keys.add(b.name[len(base):])
            except Exception:
                pass
        if self.local_dir:
            d = self.local_dir / prefix
            if d.exists():
                for p in d.glob("*.json"):
                    keys.add(prefix + p.name)
        return sorted(keys)


__all__ = ["JsonStore", "session_can_write"]
