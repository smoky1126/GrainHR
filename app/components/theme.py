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


def logo_file():
    """The logo shipped with the code, or the one kept beside company.toml."""
    if LOGO.exists():
        return LOGO
    try:
        from payroll.core.settings import load
        company = Path(str(load().get("_path") or "")).resolve().parent / "assets" / "logo.jpg"
    except (OSError, TypeError):
        return None
    return company if company.exists() else None


_logo = {"ready": False, "path": None}


def show_logo():
    if not _logo["ready"]:
        _logo["path"] = logo_file()
        _logo["ready"] = True
    if _logo["path"]:
        st.logo(str(_logo["path"]), size="large")
