"""GrainHR navigation."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.update import restart_notice


def _pages():
    return {
        "每日": [
            st.Page("pages/today.py", title="今日出勤", icon=":material/today:", default=True),
            st.Page("pages/attendance.py", title="出勤紀錄", icon=":material/calendar_month:"),
        ],
        "員工": [
            st.Page("pages/staff.py", title="員工總表", icon=":material/groups:"),
            st.Page("pages/leave.py", title="假期", icon=":material/beach_access:"),
            st.Page("pages/names.py", title="名字配對", icon=":material/link:"),
        ],
        "每月出糧": [
            st.Page("pages/records.py", title="月份紀錄", icon=":material/inventory_2:"),
            st.Page("pages/overview.py", title="總覽", icon=":material/dashboard:"),
            st.Page("pages/review.py", title="審核", icon=":material/fact_check:"),
            st.Page("pages/salary.py", title="薪金表", icon=":material/table:"),
            st.Page("pages/payout.py", title="出糧", icon=":material/payments:"),
        ],
        "系統": [
            st.Page("pages/settings.py", title="設定", icon=":material/settings:"),
        ],
    }


def main():
    st.set_page_config(page_title="GrainHR", page_icon=":material/bakery_dining:", layout="wide")
    from app.auth import allow_sign_in
    if not allow_sign_in():
        return
    page = st.navigation(_pages())
    restart_notice()
    try:
        page.run()
    except SystemExit as error:
        from app.errors import show_failure
        show_failure(error)
    except Exception as error:
        from app.errors import show_failure
        show_failure(error)


if __name__ == "__main__":
    main()
