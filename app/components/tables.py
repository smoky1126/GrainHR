import pandas as pd

from payroll.core.money import LATE_GRACE_MINUTES
from payroll.core.settings import shop_label

def style_days(days):
    """Colour clock-in and clock-out. Late over 5 minutes is red, 1 to 5 is amber, early is red, overtime is blue."""
    names = {
        "Name": "姓名", "Date": "日期", "Rosters": "更表", "Chosen shop": "採用店鋪",
        "Roster cell": "更表內容",         "DAKA in": "上班", "DAKA out": "下班",
        "DAKA in place": "上班地點", "DAKA out place": "下班地點",
        "DAKA place": "打卡地點", "Status": "情況",
    }
    shown = days.loc[:, [column for column in names if column in days.columns]].rename(columns=names)
    if "工時" in days.columns and "下班" in shown.columns:
        shown.insert(shown.columns.get_loc("下班") + 1, "工時", list(days["工時"]))
    elif "工時" in days.columns:
        shown["工時"] = list(days["工時"])
    if "採用店鋪" in shown.columns:
        shown["採用店鋪"] = shown["採用店鋪"].map(lambda value: shop_label(value) or value)
    shown["遲到"] = list(days["Late"]) if "Late" in days.columns else [0] * len(shown)
    shown["早退"] = list(days["Early"]) if "Early" in days.columns else [0] * len(shown)
    shown["加班"] = list(days["OT"]) if "OT" in days.columns else [0] * len(shown)

    def _number(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0
        return 0 if pd.isna(number) else number

    def paint(row):
        styles = [""] * len(row)
        index = {name: list(row.index).index(name) for name in row.index}
        red = "color: #C00000; font-weight: 700"
        amber = "color: #C65911; font-weight: 700"
        blue = "color: #2F5496; font-weight: 700"
        if "上班" in index and _number(row.get("遲到")) > LATE_GRACE_MINUTES:
            styles[index["上班"]] = red
        elif "上班" in index and _number(row.get("遲到")) > 0:
            styles[index["上班"]] = amber
        if "下班" in index and _number(row.get("早退")) > 0:
            styles[index["下班"]] = red
        elif "下班" in index and _number(row.get("加班")) > 0:
            styles[index["下班"]] = blue
        return styles

    return shown.style.apply(paint, axis=1)
