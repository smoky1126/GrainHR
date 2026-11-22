"""Warn when the shared code changed after this window started, so every PC runs one version."""

import os
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parents[2]
_FOLDERS = ("app", "payroll")


def _newest():
    newest = 0.0
    for folder in _FOLDERS:
        for base, _dirs, files in os.walk(_ROOT / folder):
            for name in files:
                if name.endswith((".py", ".css")):
                    try:
                        newest = max(newest, os.path.getmtime(os.path.join(base, name)))
                    except OSError:
                        pass
    return newest


_STARTED = _newest()


@st.cache_data(ttl=120, show_spinner=False)
def _current():
    return _newest()


def restart_notice():
    if os.environ.get("GRAINHR_SERVER") == "1" or os.name != "nt":
        return
    if _current() > _STARTED + 1:
        st.warning(
            "GrainHR 已更新。請關閉黑色視窗，再雙擊 GrainHR.bat，所有電腦便會用同一個版本。",
            icon=":material/system_update:",
        )
