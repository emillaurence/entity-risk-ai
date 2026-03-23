"""
src.app.styles — CSS injection for the Streamlit UI.

Call ``inject_styles()`` once at the start of ``render_layout()``.
All rules are scoped conservatively to avoid colliding with Streamlit internals.
"""

from __future__ import annotations

import streamlit as st

_CSS = """
<style>

/* ── Layout breathing room ─────────────────────────── */
section[data-testid="stMain"] > div { padding-top: 1.2rem; }
[data-testid="stHorizontalBlock"] { gap: 1.2rem; }

/* ── Typography ────────────────────────────────────── */
.stMarkdown p { line-height: 1.65; color: #1F2937; }

/* ── Metrics ───────────────────────────────────────── */
[data-testid="stMetricValue"] {
    font-size: 1.0rem !important;
    font-weight: 700 !important;
    color: #111827 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.7rem !important;
    color: #6B7280 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}

/* ── Divider ───────────────────────────────────────── */
hr { border-color: rgba(0,0,0,0.07) !important; margin: 14px 0 !important; }

/* ── Expanders ─────────────────────────────────────── */
details summary {
    font-size: 0.8em !important;
    color: #4B5563 !important;
    font-weight: 500;
}
details { border-radius: 6px !important; }

/* ── Caption ───────────────────────────────────────── */
.stCaption p {
    color: #6B7280 !important;
    font-size: 0.8em !important;
}

/* ── Text area ─────────────────────────────────────── */
textarea { font-size: 0.9em !important; }

/* ── Success / error message containers ───────────── */
[data-testid="stAlert"] { border-radius: 8px !important; }

</style>
"""


def inject_styles() -> None:
    """Inject global CSS into the Streamlit page.

    Safe to call on every rerun — Streamlit deduplicates ``st.markdown``
    calls so there is no measurable overhead.
    """
    st.markdown(_CSS, unsafe_allow_html=True)
