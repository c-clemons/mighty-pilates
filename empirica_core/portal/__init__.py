"""Empirica portal UI kit — shared Streamlit chrome, theming, auth, and widgets.

Import from the submodules or the convenience re-exports here::

    from empirica_core.portal import chrome, auth, components, export, theme
    from empirica_core.portal.app import run_app

Requires the ``portal`` extra (``pip install empirica-core[portal]``) — i.e.
Streamlit + Plotly. The util layer (``formatting``, ``months``, ``qbo``,
``datastore``) has no such dependency.
"""
from empirica_core.portal import auth, chrome, components, export, theme

__all__ = ["auth", "chrome", "components", "export", "theme"]
