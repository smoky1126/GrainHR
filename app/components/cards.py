from html import escape

import streamlit as st

from app.components.chips import _chip_html

def _safe(value):
    return escape(str(value or ""))

def page_header(title, month, subtitle="", purpose=""):
    line = purpose or subtitle
    sub = f'<p class="pay-sub">{_safe(line)}</p>' if line else ""
    st.markdown(
        f'<div class="pay-head"><h1>{_safe(title)}</h1><span class="pay-pill">{_safe(month)}</span></div>{sub}',
        unsafe_allow_html=True,
    )


def empty_state(title, reason, action_label="", target_page=""):
    """An empty screen that says why, and one button for the next step."""
    st.info(f"**{title}**\n\n{reason}")
    if action_label and target_page:
        st.page_link(target_page, label=action_label, icon=":material/arrow_forward:")


def first_tip(key, text):
    """A short tip the first time this page is opened in the session."""
    flag = f"grainhr-tip-{key}"
    if st.session_state.get(flag):
        return
    st.info(text)
    if st.button("知道了", key=f"{flag}-ok"):
        st.session_state[flag] = True
        st.rerun()

def kpi(label, value, note="", tone="info"):
    kind = tone if tone in {"ok", "todo", "block", "info", "muted", "warn", "bad"} else "info"
    st.markdown(
        f'<div class="pay-kpi pay-kpi-{kind}">'
        f'<div class="pay-kpi-label">{_safe(label)}</div>'
        f'<div class="pay-kpi-value">{_safe(value)}</div>'
        f'<div class="pay-kpi-note">{_safe(note)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )

def section(title, state, detail):
    words = {"done": "完成", "todo": "未做", "wait": "等候"}
    tones = {"done": "ok", "todo": "todo", "wait": "muted"}
    st.markdown(
        f'<div class="pay-section"><h3>{_safe(title)}</h3>{_chip_html(words.get(state, state), tones.get(state, "muted"))}</div>'
        f'<p class="pay-detail">{_safe(detail)}</p>',
        unsafe_allow_html=True,
    )

def callout(text):
    st.markdown(f'<div class="pay-callout">{_safe(text)}</div>', unsafe_allow_html=True)
