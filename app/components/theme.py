"""Load the stylesheet and the logo."""

from pathlib import Path

import streamlit as st

CSS = Path(__file__).resolve().parents[1] / "theme" / "theme.css"
LOGO = Path(__file__).resolve().parents[1] / "assets" / "logo.jpg"


def inject():
    extra = CSS.parent / "product.css"
    text = CSS.read_text(encoding="utf-8")
    if extra.exists():
        text += "\n" + extra.read_text(encoding="utf-8")
    st.markdown("<style>\n" + text + "\n</style>", unsafe_allow_html=True)


def show_logo():
    if LOGO.exists():
        st.logo(str(LOGO), size="large")
