"""Altair charts in the GrainHR colours."""

SERIES = ["#3A3A3A", "#C8963E", "#2F5D9E", "#2E7D5B", "#9B5DE5", "#C0392B"]
STATUS = {
    "ok": "#2E7D5B",
    "warn": "#D98E04",
    "bad": "#C0392B",
    "info": "#2F5D9E",
    "muted": "#8A8A8A",
}


def chart(spec):
    import altair as alt

    return spec.configure(background="transparent").configure_axis(
        grid=False, labelColor="#6B6B6B", titleColor="#3A3A3A", labelFont="Noto Sans TC",
    ).configure_legend(labelColor="#3A3A3A", title=None).configure_view(strokeWidth=0)


def doughnut(frame, name, value, title, colors=None):
    import altair as alt

    spec = alt.Chart(frame).mark_arc(innerRadius=48).encode(
        theta=alt.Theta(value, type="quantitative"),
        color=alt.Color(
            name, type="nominal",
            scale=alt.Scale(range=colors or SERIES),
            legend=alt.Legend(orient="bottom"),
        ),
        tooltip=[name, value],
    ).properties(height=210, title=title)
    return chart(spec)


def bars(frame, x, y, color=None, title=""):
    import altair as alt

    encoding = {"x": alt.X(x, type="nominal", title=None), "y": alt.Y(y, type="quantitative", title=None)}
    if color:
        encoding["color"] = alt.Color(color, type="nominal", scale=alt.Scale(range=SERIES))
    spec = alt.Chart(frame).mark_bar(cornerRadiusEnd=4).encode(**encoding).properties(height=200, title=title)
    return chart(spec)


def horizontal_bars(frame, label, value, title=""):
    """One bar per person. The longest bar is at the top."""
    import altair as alt

    spec = alt.Chart(frame).mark_bar(cornerRadiusEnd=4, color="#C0392B").encode(
        y=alt.Y(label, type="nominal", sort=alt.EncodingSortField(field=value, order="descending"), title=None),
        x=alt.X(value, type="quantitative", title="分鐘"),
        tooltip=[label, alt.Tooltip(value, format=".0f"), "天數"],
    ).properties(height=max(120, 36 * len(frame)), title=title)
    return chart(spec)
