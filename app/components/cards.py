import streamlit as st

from app.components.chips import _chip_html

def page_header(title, month, subtitle="", purpose=""):
    line = purpose or subtitle
    sub = f'<p class="pay-sub">{line}</p>' if line else ""
    st.markdown(
        f'<div class="pay-head"><h1>{title}</h1><span class="pay-pill">{month}</span></div>{sub}',
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
