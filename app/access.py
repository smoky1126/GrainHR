"""Who can see salary, identity numbers, and bank details."""

import streamlit as st

from app.lock import _user
from payroll.core.settings import role_for


def current_role():
    return role_for(_user())


def hide_pay_page():
    """Stop a pay page when the signed-in role is a shop viewer."""
    if current_role() == "viewer":
        st.error("這頁有薪金資料，店長不能查看。")
        st.stop()
