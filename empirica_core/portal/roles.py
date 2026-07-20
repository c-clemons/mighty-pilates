"""Role-based access on top of the identity Cloudflare Access provides.

Cloudflare Access is set to admit *anyone* who can prove they own an email
(one-time PIN). This module is the real gate: it maps a verified email to a
role, and the app shows only what that role allows. An in-app admin assigns
roles, so the client controls their own users without touching Cloudflare.

State lives in a private GCS bucket (durable across Cloud Run redeploys), one
`roles/<app>.json` per portal, with a local-file fallback for dev.

Fail-closed: on Cloud Run, no verified identity ⇒ no access. The dev fallback
only applies off Cloud Run (no ``K_SERVICE`` env var).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# --- role hierarchy ---------------------------------------------------------
ROLES = ("admin", "management", "employee", "investor")
_LEVEL = {"investor": 1, "employee": 2, "management": 3, "admin": 4}


def level(role: Optional[str]) -> int:
    return _LEVEL.get((role or "").lower(), 0)


def can_view(role: Optional[str], min_role: str) -> bool:
    """True when ``role`` is at least as privileged as ``min_role``."""
    return level(role) >= level(min_role)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- identity ---------------------------------------------------------------
def resolve_identity() -> Optional[str]:
    """The verified email for the current request, or None (fail-closed).

    On Cloud Run (``K_SERVICE`` set) the only trusted source is the Cloudflare
    Access header — no header means no access. Off Cloud Run (local dev) we fall
    back to ``LOCAL_DEV_EMAIL`` so you're not locked out of your own machine.
    """
    from empirica_core.portal.auth import proxy_identity

    who = proxy_identity()
    if who:
        return who.lower()
    if os.environ.get("K_SERVICE"):
        return None  # on Cloud Run with no Access header — deny
    dev = os.environ.get("LOCAL_DEV_EMAIL")
    return dev.lower() if dev else None


# --- store ------------------------------------------------------------------
class RoleStore:
    """Durable email→role store, GCS-backed with a local-file fallback.

    Data shape: ``{email: {"role": str, "added_by": str, "added_at": iso}}``
    plus a top-level ``"_pending": [emails]`` list for access requests.

    ``bootstrap_admins`` are always admins regardless of the stored file — this
    seeds the very first admin so someone can reach the admin UI.
    """

    def __init__(
        self,
        app_key: str,
        *,
        bucket: Optional[str] = None,
        bootstrap_admins=(),
        local_path: Optional[Path] = None,
    ) -> None:
        self.app_key = app_key
        self.bucket = bucket or os.environ.get("ROLES_BUCKET")
        self.bootstrap = {e.lower() for e in bootstrap_admins}
        self.local_path = Path(local_path) if local_path else None

    def _blob_name(self) -> str:
        return f"roles/{self.app_key}.json"

    # --- backend I/O --------------------------------------------------------
    def _load(self) -> dict:
        if self.bucket:
            try:
                from google.cloud import storage

                blob = storage.Client().bucket(self.bucket).blob(self._blob_name())
                if blob.exists():
                    return json.loads(blob.download_as_text())
                return {}
            except Exception:
                pass  # fall through to local
        if self.local_path and self.local_path.exists():
            return json.loads(self.local_path.read_text())
        return {}

    def _save(self, data: dict) -> None:
        payload = json.dumps(data, indent=2)
        if self.bucket:
            try:
                from google.cloud import storage

                blob = storage.Client().bucket(self.bucket).blob(self._blob_name())
                blob.upload_from_string(payload, content_type="application/json")
                return
            except Exception:
                pass
        if self.local_path:
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            self.local_path.write_text(payload)

    # --- queries ------------------------------------------------------------
    def role_for(self, email: Optional[str]) -> Optional[str]:
        if not email:
            return None
        e = email.lower()
        if e in self.bootstrap:
            return "admin"
        rec = self._load().get(e)
        return rec.get("role") if isinstance(rec, dict) else None

    def all_users(self) -> list:
        data = self._load()
        rows = [
            {"email": e, **rec}
            for e, rec in data.items()
            if not e.startswith("_") and isinstance(rec, dict)
        ]
        # surface bootstrap admins that aren't explicitly stored
        stored = {r["email"] for r in rows}
        for e in sorted(self.bootstrap - stored):
            rows.append({"email": e, "role": "admin", "added_by": "bootstrap", "added_at": ""})
        return sorted(rows, key=lambda r: (level(r["role"]) * -1, r["email"]))

    def pending(self) -> list:
        return list(self._load().get("_pending", []))

    # --- mutations ----------------------------------------------------------
    def set_role(self, email: str, role: str, by: str) -> None:
        if role not in ROLES:
            raise ValueError(f"unknown role: {role}")
        data = self._load()
        data[email.lower()] = {"role": role, "added_by": by, "added_at": _now()}
        pend = data.get("_pending", [])
        data["_pending"] = [p for p in pend if p.lower() != email.lower()]
        self._save(data)

    def revoke(self, email: str) -> None:
        if email.lower() in self.bootstrap:
            raise ValueError("cannot revoke a bootstrap admin (edit app config instead)")
        data = self._load()
        data.pop(email.lower(), None)
        self._save(data)

    def request_access(self, email: str) -> None:
        if not email:
            return
        data = self._load()
        pend = set(p.lower() for p in data.get("_pending", []))
        if email.lower() not in pend and email.lower() not in data:
            pend.add(email.lower())
            data["_pending"] = sorted(pend)
            self._save(data)


# --- landing page -----------------------------------------------------------
def render_landing(email: Optional[str], app_name: str, store: "RoleStore") -> None:
    """The gate everyone hits before a role is assigned."""
    import streamlit as st

    st.title(app_name)
    if not email:
        st.error("You're not signed in. Please reload and sign in with your email.")
        return

    st.info(f"You're signed in as **{email}**.")
    st.warning(
        "Your access is pending. An administrator needs to grant you a role "
        "before you can view the dashboard."
    )
    if email.lower() in [p.lower() for p in store.pending()]:
        st.caption("✓ Your access request has been sent — check back soon.")
    elif st.button("Request access", type="primary"):
        store.request_access(email)
        st.success("Request sent. Your administrator will grant you access.")
        st.rerun()


__all__ = [
    "ROLES", "level", "can_view", "resolve_identity", "RoleStore", "render_landing",
]
