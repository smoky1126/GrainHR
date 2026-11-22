"""The person using GrainHR. A server uses Google sign-in. A PC uses the Windows name."""

import os

import streamlit as st


def auth_enabled():
    """True only when this copy has a secrets.toml [auth] section."""
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def current_user():
    if auth_enabled():
        user = st.user
        if not getattr(user, "is_logged_in", False):
            return ""
        return str(getattr(user, "email", "") or "").strip().lower()
    return os.environ.get("USERNAME") or os.environ.get("USER") or "user"


def allow_sign_in():
    """Draw the gate. Return True when this person may use the app."""
    if not auth_enabled():
        return True
    if not getattr(st.user, "is_logged_in", False):
        from app.components.theme import show_logo
        show_logo()
        st.title("GrainHR")
        st.write("請用公司 Google 帳戶登入。登入後才可以看員工、出勤和糧單。")
        if st.button("登入", type="primary", icon=":material/login:"):
            st.login("google")
        return False
    from payroll.core.settings import _user_row

    who = current_user()
    if not _user_row(who):
        st.error(f"沒有權限。{who} 不在公司名單裡。")
        st.caption("請通知管理員把這個電郵加入名單。")
        if st.button("登出"):
            st.logout()
        if st.button("用另一個帳戶登入", icon=":material/switch_account:"):
            st.logout()
        return False
    with st.sidebar:
        if st.button("登出", key="grainhr-logout"):
            st.logout()
    return True
