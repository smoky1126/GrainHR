"""GrainHR navigation."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.update import restart_notice


def _pages():
    # This folder must not be named pages. Streamlit would then use the file
    # names as the menu and drop these titles when a page is refreshed.
    return {
        "每日": [
            st.Page("screens/today.py", title="今日出勤", icon=":material/today:", default=True),
        ],
        "員工": [
            st.Page("screens/staff.py", title="員工總表", icon=":material/groups:"),
            st.Page("screens/leave.py", title="假期", icon=":material/beach_access:"),
            st.Page("screens/names.py", title="名字配對", icon=":material/link:"),
        ],
        "每月出糧": [
            st.Page("screens/attendance.py", title="出勤紀錄", icon=":material/calendar_month:"),
            st.Page("screens/review.py", title="審核", icon=":material/fact_check:"),
            st.Page("screens/salary.py", title="薪金表", icon=":material/table:"),
            st.Page("screens/payout.py", title="出糧", icon=":material/payments:"),
            st.Page("screens/overview.py", title="總覽", icon=":material/dashboard:"),
            st.Page("screens/records.py", title="月份紀錄", icon=":material/inventory_2:"),
        ],
        "系統": [
            st.Page("screens/guide.py", title="使用說明", icon=":material/menu_book:"),
            st.Page("screens/settings.py", title="設定", icon=":material/settings:"),
        ],
    }


def _run_page(page):
    import os
    import time

    started = time.perf_counter()
    try:
        page.run()
    finally:
        if os.environ.get("GRAINHR_TIMING") == "1":
            from payroll.core.settings import actor, role_for
            elapsed = time.perf_counter() - started
            title = getattr(page, "title", "") or "page"
            print(f"GRAINHR_TIMING {title} {role_for(actor())} {elapsed:.3f}", flush=True)


def main():
    st.set_page_config(page_title="GrainHR", page_icon=":material/bakery_dining:", layout="wide")
    from app.auth import allow_sign_in
    if not allow_sign_in():
        return
    page = st.navigation(_pages(), expanded=True)
    restart_notice()
    try:
        _run_page(page)
    except SystemExit as error:
        from app.errors import show_failure
        show_failure(error)
    except Exception as error:
        from app.errors import show_failure
        show_failure(error)


if __name__ == "__main__":
    main()
