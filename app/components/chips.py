import streamlit as st

from app.components.format import hk

def _chip_html(text, tone):
    safe = "ok" if tone == "ok" else tone if tone in {"todo", "block", "info", "muted"} else "muted"
    return f'<span class="pay-chip pay-chip-{safe}">{text}</span>'

def chip(text, tone="info"):
    st.markdown(_chip_html(text, tone), unsafe_allow_html=True)

def chips(items):
    """items is a list of (text, tone)."""
    st.markdown("".join(_chip_html(text, tone) for text, tone in items), unsafe_allow_html=True)

def legend():
    chips([
        ("遲到超過 5 分鐘", "block"),
        ("遲到 5 分鐘以內", "todo"),
        ("早退", "block"),
        ("加班", "info"),
    ])

def stepper(status):
    steps = (("出勤", "daka"), ("新同事", "joiners"), ("審核", "problems"), ("出糧", "pay"))
    marks = {"done": "✓", "todo": "!", "wait": "·"}
    items = []
    for name, key in steps:
        state = status.get(key, "wait")
        items.append(
            f'<li class="pay-step-{state}"><span>{marks.get(state, "·")}</span>{name}</li>'
        )
    st.sidebar.markdown(f'<ol class="pay-steps">{"".join(items)}</ol>', unsafe_allow_html=True)
