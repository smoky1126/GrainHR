"""Short instructions for the people who use GrainHR every day."""

import streamlit as st

from app.components.cards import page_header
from app.components.theme import inject, show_logo
from app.context import _context


def page_guide():
    inject()
    show_logo()
    _context(payroll=False)
    page_header("使用說明", "GrainHR", purpose="日常怎麼用，以及去哪裡找舊資料。")
    st.page_link("screens/today.py", label="今日出勤", icon=":material/today:")
    with st.container(border=True):
        st.markdown("**登入**")
        st.markdown("打開網站後，用公司 Google 帳戶登入一次。登出在左邊選單。")
    with st.container(border=True):
        st.markdown("**每天**")
        st.markdown(
            "打開「今日出勤」，看誰應到、誰已打卡。"
            "左邊的月份預設是尚未出糧的月份。換月時，選單會標明「已出糧」或「進行中」。"
        )
    with st.container(border=True):
        st.markdown("**月底出糧**")
        st.markdown(
            "1. 出勤紀錄：確認打卡和更表。需要最新打卡時，按「立即同步 DAKA」。\n"
            "2. 名字配對：更表上的名字要對到員工。\n"
            "3. 審核：處理遲到、加班和例外，然後批准。\n"
            "4. 出糧：選日期，按「製作全部糧單」。"
        )
    with st.container(border=True):
        st.markdown("**找以前的糧單和更表**")
        st.markdown(
            "左邊選該月，打開「月份紀錄」。"
            "全職、第二間公司、兼職和寫字樓分開放。"
            "按下載才會讀取檔案。"
        )
        st.page_link("screens/records.py", label="前往月份紀錄", icon=":material/inventory_2:")
    with st.container(border=True):
        st.markdown("**誰看得到寫字樓薪金**")
        st.markdown("管理員看得到寫字樓的薪金、強積金和銀行資料。HR 同事看得到出勤和假期，但看不到這些金額。")
    with st.container(border=True):
        st.markdown("**打卡尚未更新**")
        st.markdown(
            "「今日出勤」或「出勤紀錄」顯示未同步時，按「立即同步 DAKA」，等一兩分鐘再看。"
            "已經出糧的月份不會再計算，只供查看。"
        )
