"""The person using GrainHR.

The website trusts the Cloudflare Access sign-in. A PC uses the Windows name,
or its own Google button when this copy has an [auth] section.
"""

import os
from html import escape
from urllib.parse import urlsplit

import streamlit as st


def classify_secrets(loader):
    """on when [auth] exists, off when there is no secrets file, broken otherwise."""
    from streamlit.errors import StreamlitSecretNotFoundError
    try:
        return "on" if loader() else "off"
    except StreamlitSecretNotFoundError as error:
        if getattr(error, "error_id", "") == "no-secrets-found":
            return "off"
        return "broken"
    except Exception:
        return "broken"


def secrets_state():
    return classify_secrets(lambda: "auth" in st.secrets)


def auth_enabled():
    """True only when this copy has a readable secrets.toml [auth] section."""
    return secrets_state() == "on"


def current_user():
    from app.access_token import access_email, access_required

    if access_required():
        return access_email()
    if auth_enabled():
        user = st.user
        if not getattr(user, "is_logged_in", False):
            return ""
        return str(getattr(user, "email", "") or "").strip().lower()
    return os.environ.get("USERNAME") or os.environ.get("USER") or "user"


def allow_sign_in():
    """Draw the gate. Return True when this person may use the app."""
    from app.access_token import access_required

    if access_required():
        return _allow_access()
    if secrets_state() == "broken":
        st.error("登入設定無法讀取，已停止開放。請通知管理員。")
        return False
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
    return _allow_known_user(current_user(), st.logout)


def _allow_access():
    from app.access_token import access_email
    from app.components.theme import show_logo

    who = access_email()
    if not who:
        show_logo()
        st.title("GrainHR")
        st.write("請用公司 Google 帳戶登入。登入後才可以看員工、出勤和糧單。")
        st.caption("若這個畫面一直在，請重新登入。")
        _logout_link("重新登入")
        return False
    return _allow_known_user(who, None)


def _allow_known_user(who, streamlit_logout):
    from payroll.core.settings import _user_row, role_for

    if not _user_row(who) or role_for(who) == "none":
        st.error(f"沒有權限。{who} 不在公司名單裡。")
        st.caption("請通知管理員把這個電郵加入名單。")
        if streamlit_logout is None:
            _logout_link("用另一個帳戶登入")
        else:
            if st.button("登出"):
                streamlit_logout()
            if st.button("用另一個帳戶登入", icon=":material/switch_account:"):
                streamlit_logout()
        return False
    with st.sidebar:
        if streamlit_logout is None:
            _logout_link("登出")
        elif st.button("登出", key="grainhr-logout"):
            from app.lock import release_all
            release_all()
            streamlit_logout()
    return True


def logout_url():
    """The company entrance sign-out page for the site this browser opened."""
    try:
        parts = urlsplit(str(st.context.url or ""))
    except Exception:
        parts = urlsplit("")
    host = parts.hostname or ""
    if parts.scheme in {"http", "https"} and host:
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{host}{port}/cdn-cgi/access/logout"
    return "/cdn-cgi/access/logout"


def _logout_link(label):
    # The native link button opens a new tab, which would leave this tab signed in.
    url = escape(logout_url(), quote=True)
    if st.button(label, key=f"grainhr-out-{label}"):
        from app.lock import release_all
        release_all()
        st.html(f'<meta http-equiv="refresh" content="0;url={url}">')
