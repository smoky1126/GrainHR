"""Badges, banners, empty states, and file tiles."""

import html

import streamlit as st


def badge(text, tone="muted"):
    safe = html.escape(str(text))
    kind = tone if tone in {"ok", "warn", "bad", "info", "muted"} else "muted"
    st.markdown(f'<span class="gh-badge gh-badge-{kind}">{safe}</span>', unsafe_allow_html=True)


def banner(text, tone="warn"):
    safe = html.escape(str(text))
    kind = tone if tone in {"ok", "warn", "bad", "info", "muted"} else "warn"
    st.markdown(
        f'<div class="gh-badge gh-badge-{kind}" style="display:block;border-radius:12px;padding:8px 14px;margin:0 0 12px 0">{safe}</div>',
        unsafe_allow_html=True,
    )


def empty_state(title, detail):
    st.markdown(
        f'<div class="gh-empty"><strong>{html.escape(title)}</strong>{html.escape(detail)}</div>',
        unsafe_allow_html=True,
    )


def file_tile(name, detail):
    st.markdown(
        f'<div class="gh-card gh-file"><div><strong>{html.escape(name)}</strong><div class="pay-sub">{html.escape(detail)}</div></div></div>',
        unsafe_allow_html=True,
    )


def freshness(label, relative, exact, tone="ok"):
    kind = tone if tone in {"ok", "warn", "bad", "muted"} else "muted"
    title = html.escape(exact or "")
    st.markdown(
        f'<span class="gh-badge gh-badge-{kind}" title="{title}">{html.escape(label)} · {html.escape(relative)}</span>',
        unsafe_allow_html=True,
    )
