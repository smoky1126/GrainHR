import streamlit as st

from app.components.chips import _chip_html

def page_header(title, month, subtitle=""):
    sub = f'<p class="pay-sub">{subtitle}</p>' if subtitle else ""
    st.markdown(
        f'<div class="pay-head"><h1>{title}</h1><span class="pay-pill">{month}</span></div>{sub}',
        unsafe_allow_html=True,
    )

def kpi(label, value, note="", tone="info"):
    st.markdown(
        f'<div class="pay-kpi pay-kpi-{tone}">'
        f'<div class="pay-kpi-label">{label}</div>'
        f'<div class="pay-kpi-value">{value}</div>'
        f'<div class="pay-kpi-note">{note}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )

def section(title, state, detail):
    words = {"done": "完成", "todo": "未做", "wait": "等候"}
    tones = {"done": "ok", "todo": "todo", "wait": "muted"}
    st.markdown(
        f'<div class="pay-section"><h3>{title}</h3>{_chip_html(words.get(state, state), tones.get(state, "muted"))}</div>'
        f'<p class="pay-detail">{detail}</p>',
        unsafe_allow_html=True,
    )

def callout(text):
    st.markdown(f'<div class="pay-callout">{text}</div>', unsafe_allow_html=True)
