"""Link a payslip name to the name used on the roster and in DAKA."""

import re


# Characters that differ between the payslip and the roster for the same person.
_SAME = str.maketrans({
    "華": "华", "顯": "显", "曉": "晓", "門": "门", "東": "东", "張": "张",
    "劉": "刘", "陳": "陈", "黃": "黄", "吳": "吴", "羅": "罗", "龍": "龙",
    "偉": "伟", "傑": "杰", "麗": "丽", "愛": "爱", "國": "国", "灣": "湾",
    "麥": "麦", "葉": "叶", "莊": "庄", "鍾": "钟", "歐": "欧", "陽": "阳",
    "錫": "鍚",
})


def chinese(text):
    raw = "".join(re.findall(r"[\u4e00-\u9fff]", text or ""))
    return raw.translate(_SAME)


def english_tokens(text):
    return {token.lower() for token in re.findall(r"[A-Za-z]{2,}", text or "")}


# Office roster uses English nicknames. Bosses are not in this map.
_OFFICE = {
    "陳家樂": "James Chan",
    "楊宛婷": "Alice Yeung",
    "李嘉俊": "Sam Lee",
    "梁曉雯": "Carmen Leung",
    "梁穎儀": "Milly Leung",
    "童瑋琳": "Shirley Tung",
}


def match_roster_name(slip_name, name_en, name_zh, roster_names):
    """Return the roster name, or '' when there is not exactly one candidate."""
    target = chinese(name_zh) or chinese(slip_name)
    office = {chinese(key): value for key, value in _OFFICE.items()}
    if target in office:
        wanted = office[target].lower()
        for name in roster_names:
            if str(name).strip().lower() == wanted:
                return name
    if target:
        exact = [name for name in roster_names if chinese(name) == target]
        if len(exact) == 1:
            return exact[0]
        contained = [
            name for name in roster_names
            if chinese(name) and (chinese(name) in target or target in chinese(name))
        ]
        if len(contained) == 1:
            return contained[0]
    tokens = english_tokens(name_en) or english_tokens(slip_name)
    if not tokens:
        return ""
    scored = []
    for name in roster_names:
        theirs = english_tokens(name)
        if not theirs:
            continue
        if tokens <= theirs or theirs <= tokens or len(tokens & theirs) >= 2:
            scored.append(name)
    if len(scored) == 1:
        return scored[0]
    return ""
