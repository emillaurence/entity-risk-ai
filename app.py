"""
app.py — Streamlit entry point.

Responsibilities (exhaustive):
1. Configure the Streamlit page (title, icon, layout).
2. Delegate all rendering to src.app.layout.render_layout().

Nothing else belongs here.  All application logic lives in src/app/.
"""

import streamlit as st

from src.app.layout import render_layout

st.set_page_config(
    page_title="Entity Risk Investigation",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

render_layout()
