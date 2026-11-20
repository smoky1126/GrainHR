"""What this installation is using. Paths stay on this computer."""

from pathlib import Path

import streamlit as st

from app.components.cards import page_header
from app.components.theme import inject, show_logo
from app.lock import _user
from payroll.core.settings import daka, display_name, is_private, role_for


def page_settings():
    inject()
    show_logo()
    who = _user()
    roles = {"admin": "HR 管理員", "hr": "HR 同事", "viewer": "店長"}
    page_header("設定", "GrainHR v1.0.0")
    st.markdown(f"**{display_name(who)}** · {roles.get(role_for(who), 'HR 同事')}")
    if not is_private():
        st.info("現在用的是 company.example.toml。把 company.toml 放在程式旁邊，就會用你公司的名稱。")
    info = daka()
    st.markdown("**DAKA**")
    st.write(f"伺服器：{info.get('server') or '未設定'}")
    st.write(f"匯出位置：{info.get('remote') or '未設定'}")
    version = Path(__file__).resolve().parents[2] / "VERSION"
    if version.exists():
        st.caption(version.read_text(encoding="utf-8").strip())
