"""Turn a crash into a short message and a log file."""

import os
import sys
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


def notify(subject, body):
    """Record an alert. Email it when GRAINHR_ALERT_TO is set and sendmail exists."""
    import shutil
    import subprocess
    write_log(f"ALERT {subject}\n{body}")
    recipient = os.environ.get("GRAINHR_ALERT_TO", "").strip()
    program = shutil.which("sendmail")
    if not recipient or not program:
        return
    message = f"To: {recipient}\nSubject: GrainHR {subject}\n\n{body}\n"
    try:
        subprocess.run([program, "-t"], input=message, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return


def show_failure(error):
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    who = actor()
    if isinstance(error, SystemExit):
        text = str(error).strip() or "已停止。"
        write_log(f"{when} {who} {text}")
        st.error(text)
        return
    code = datetime.now().strftime("%m%d%H%M%S")
    detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    write_log(f"{when} {who} {code}\n{detail}")
    notify(f"頁面錯誤 {code}", f"{when} {who}\n編號 {code}")
    print(detail, file=sys.stderr, flush=True)
    from payroll.core.settings import role_for
    st.error(f"這頁出了問題。請把編號 {code} 告訴管理員。")
    if role_for(who) == "admin":
        with st.expander("詳細內容"):
            st.code(detail)
