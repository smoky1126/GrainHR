"""Turn a crash into a short message and a log file."""

import traceback
from datetime import datetime

import streamlit as st

from payroll.core.config import home
from payroll.core.settings import actor


def log_path():
    folder = home() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "grainhr.log"


def write_log(message):
    path = log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message)
        if not message.endswith("\n"):
            handle.write("\n")
    return path


def show_failure(error):
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    who = actor()
    if isinstance(error, SystemExit):
        text = str(error).strip() or "已停止。"
        write_log(f"{when} {who} {text}")
        st.error(text)
        return
    detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    write_log(f"{when} {who}\n{detail}")
    st.error("這頁出了問題。詳細內容已寫入 data/logs/grainhr.log。")
