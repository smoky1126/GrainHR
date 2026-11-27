"""Tap Export in the real DAKA app, then save the file on the emulator.

The password is never stored or typed. steps.json holds the labels from the
one-time calibration. Screen coordinates are not used.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = ROOT / "steps.json"
OUTBOX = ROOT / "outbox"
LOGGED_OUT = "DAKA 已登出，請在模擬器重新登入"
DENY = ("Don’t allow", "Don't allow")


def _status(ok, message, files=None):
    OUTBOX.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": ok,
        "message": message,
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "files": files or [],
    }
    (OUTBOX / "status.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(message)
    return 0 if ok else 1


def _steps():
    if not STEPS.exists():
        return {}
    return json.loads(STEPS.read_text(encoding="utf-8"))


def _adb(*args, timeout=30):
    return subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout)


def _boot():
    deadline = time.time() + 180
    while time.time() < deadline:
        done = _adb("shell", "getprop", "sys.boot_completed", timeout=15)
        if done.returncode == 0 and (done.stdout or "").strip() == "1":
            return True
        time.sleep(3)
    return False


def _device():
    try:
        import uiautomator2 as device
    except ImportError:
        return None
    return device.connect()


def _logged_out(device, markers):
    for text in markers or ["登入", "登錄", "Login"]:
        if device(textContains=text).exists:
            return True
    return False


def _quiet_location(package):
    for op in ("COARSE_LOCATION", "FINE_LOCATION"):
        _adb("shell", "appops", "set", package, op, "ignore")


def _deny_location(device):
    if not device(textContains="location").exists and not device(textContains="位置").exists:
        return
    for label in DENY:
        button = device(text=label)
        if button.exists:
            button.click()
            time.sleep(1)
            return
    nodes = device(textContains="allow")
    for index in range(nodes.count):
        item = nodes[index]
        folded = item.get_text().replace("’", "").replace("'", "").lower()
        if "dont" in folded:
            item.click()
            time.sleep(1)
            return


def _click_parent(device, xpath, missing):
    node = device.xpath(xpath)
    if not node.exists:
        raise SystemExit(missing)
    node.click()


_DATE_TEXT = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_ZH_MONTHS = ["", "一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"]
_CALENDAR_DAY = re.compile(r"(\d{1,2}) (一月|二月|三月|四月|五月|六月|七月|八月|九月|十月|十一月|十二月) (\d{4})")
_EXPORT_TABS = ("报表汇出", "報表匯出", "报表导出", "報表導出")
_EXPORT_ACTIONS = (
    "匯出", "导出", "汇出", "Export",
    "导出报表", "匯出報表", "汇出报表", "导出文件", "匯出文件",
    "下载", "下載", "分享",
)


def _export_targets(plan):
    """Labels that open the DAKA export page. The app now uses 报表汇出 instead of 匯出."""
    labels = []
    for label in [plan.get("open")] + _as_list(plan.get("open_text")) + list(_EXPORT_TABS) + list(_EXPORT_ACTIONS):
        if label and label not in labels:
            labels.append(label)
    return labels


def _export_actions(plan):
    """The button that creates the file. The 报表汇出 tab only opens that page."""
    labels = []
    for label in [plan.get("export")] + list(_EXPORT_ACTIONS):
        if label and label not in labels and label not in _EXPORT_TABS:
            labels.append(label)
    return labels


def _chinese_dates(device):
    xml = device.dump_hierarchy()
    found = []
    for node in re.findall(r"<node [^>]+>", xml):
        for attr in ("text", "content-desc"):
            match = re.search(attr + r'="([^"]*)"', node)
            if not match or not _DATE_TEXT.search(match.group(1)):
                continue
            label = match.group(1).strip()
            if label not in found:
                found.append(label)
    return found


def _export_page_open(device, plan):
    if _showing(device, _as_list(plan.get("dialog"))):
        return True
    return _showing(device, _EXPORT_TABS) and bool(_chinese_dates(device))


def _screen_labels(device):
    xml = device.dump_hierarchy()
    labels = []
    for node in re.findall(r"<node [^>]+>", xml):
        text = re.search(r'text="([^"]*)"', node)
        desc = re.search(r'content-desc="([^"]*)"', node)
        for match in (text, desc):
            label = (match.group(1) if match else "").strip()
            if not label or len(label) > 32 or label in labels or "@" in label:
                continue
            if re.search(r"\d{6,}", label):
                continue
            if any(word in label for word in ("signal", "Battery", "notification", "Wifi", "Phone")):
                continue
            labels.append(label)
    interesting = [label for label in labels if any(word in label for word in ("汇出", "匯出", "导出", "導出", "Export", "内勤", "外勤"))]
    ordered = interesting + [label for label in labels if label not in interesting]
    return ordered[:12]


def _as_list(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value] if value else []


def _showing(device, labels):
    for label in labels:
        if device(text=label).exists or device(description=label).exists:
            return True
    return False


def _tap_label(device, label):
    parent = device.xpath('//*[@text="%s"]/ancestor::*[@clickable="true"][1]' % label)
    if parent.exists:
        parent.click()
        return True
    parent = device.xpath('//*[@content-desc="%s"]/ancestor::*[@clickable="true"][1]' % label)
    if parent.exists:
        parent.click()
        return True
    node = device(text=label)
    if node.exists:
        node.click()
        return True
    node = device(description=label)
    if node.exists:
        node.click()
        return True
    return False


def _open_export(device, plan):
    """Leave the company list if it is showing, then open the export dialog."""
    dialogs = _as_list(plan.get("dialog"))
    opens = _export_targets(plan)
    company = plan.get("company") or ""
    backs = _as_list(plan.get("back"))
    deadline = time.time() + 40
    while time.time() < deadline:
        _deny_location(device)
        if device(text="Sharing 1 file").exists or device(text=plan.get("save_label") or "").exists:
            grabbed = _grab_open_share(device, plan)
            if grabbed is not None:
                return grabbed
            time.sleep(1)
            continue
        if _calendar_open(device):
            _dismiss_calendar(device)
            time.sleep(1)
            continue
        if _export_page_open(device, plan):
            return None
        if _showing(device, backs):
            for label in ("Navigate up", "Back", "返回", "關閉", "关闭"):
                if _tap_label(device, label):
                    break
            else:
                _adb("shell", "input", "keyevent", "4")
            time.sleep(1)
            continue
        if device(text="您的公司").exists:
            for label in ("出勤", "打卡", "Attendance", "Menu"):
                if _tap_label(device, label):
                    time.sleep(2)
                    break
            continue
        if device(text="考勤").exists and not _showing(device, opens):
            _tap_label(device, "考勤")
            time.sleep(2)
            continue
        for label in opens:
            if not label:
                continue
            if _tap_label(device, label):
                time.sleep(2)
                if _export_page_open(device, plan):
                    return None
        time.sleep(1)
    seen = "、".join(_screen_labels(device))
    if seen:
        raise SystemExit("畫面上找不到匯出按鈕。目前畫面：%s" % seen)
    raise SystemExit("畫面上找不到匯出按鈕。")


def _day_desc(when):
    month = _ZH_MONTHS[when.month]
    padded = f"{when.day:02d} {when.strftime('%B')} {when.year}"
    plain = f"{when.day} {when.strftime('%B')} {when.year}"
    chinese = f"{when.year}年{when.month}月{when.day}日"
    zh_padded = f"{when.day:02d} {month} {when.year}"
    zh_plain = f"{when.day} {month} {when.year}"
    return padded, plain, chinese, zh_padded, zh_plain


def _calendar_open(device):
    return _CALENDAR_DAY.search(device.dump_hierarchy()) is not None


def _dismiss_calendar(device):
    for label in ("取消", "Cancel", "關閉", "关闭"):
        if _tap_label(device, label):
            return True
    _adb("shell", "input", "keyevent", "4")
    return True


def _visible_month(device):
    xml = device.dump_hierarchy()
    found = re.findall(r'content-desc="(\d{1,2}) ([A-Za-z]+) (\d{4})"', xml)
    if found:
        _day, month, year = found[0]
        return date(int(year), time.strptime(month, "%B").tm_mon, 1)
    found = _CALENDAR_DAY.search(xml)
    if found:
        year, month_name = int(found.group(3)), found.group(2)
        return date(year, _ZH_MONTHS.index(month_name), 1)
    found = re.findall(r'(?:text|content-desc)="(\d{4})年(\d{1,2})月', xml)
    if not found:
        return None
    year, month = found[0]
    return date(int(year), int(month), 1)


def _confirm(device):
    for label in ("OK", "確定", "确定", "确认", "確認"):
        if _tap_label(device, label):
            return True
    return False


def _set_date(device, label, when):
    _deny_location(device)
    labels = _as_list(label)
    field = None
    for text in labels:
        field = device(text=text)
        if field.exists:
            break
    else:
        field = None
    if field is None or not field.exists:
        dates = _chinese_dates(device)
        index = 1 if any(word in "".join(labels) for word in ("End", "結束", "结束")) and len(dates) > 1 else 0
        if not dates or not _tap_label(device, dates[index]):
            raise SystemExit("畫面上找不到：%s。目前畫面：%s" % ("、".join(labels), "、".join(_screen_labels(device))))
    else:
        field.click()
    time.sleep(1)
    for _ in range(8):
        for desc in _day_desc(when):
            if _tap_label(device, desc):
                time.sleep(0.4)
                if not _confirm(device):
                    raise SystemExit("日曆沒有確認按鈕。目前畫面：%s" % "、".join(_screen_labels(device)))
                time.sleep(0.8)
                return
        shown = _visible_month(device)
        if shown is None:
            raise SystemExit("日曆沒有打開：%s" % "、".join(labels))
        earlier = (when.year, when.month) < (shown.year, shown.month)
        control = "Previous month" if earlier else "Next month"
        button = device(description=control)
        if not button.exists:
            control = "上个月" if earlier else "下个月"
            button = device(description=control)
        if not button.exists:
            button = device(text=control)
        if not button.exists:
            raise SystemExit(f"日曆找不到 {when.isoformat()}")
        button.click()
        time.sleep(0.5)
    raise SystemExit(f"日曆找不到 {when.isoformat()}")


def _downloads():
    done = _adb("shell", "ls", "-t", "/sdcard/Download")
    return [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]


def _saver_activity(package):
    dump = _adb("shell", "dumpsys", "package", package).stdout or ""
    match = re.search(r"([\w.]+SaveActivity)", dump)
    if match:
        return f"{package}/{match.group(1)}"
    return f"{package}/{package}.SaveActivity"


def _shared_uri():
    dump = _adb("shell", "dumpsys", "activity", "activities").stdout or ""
    found = re.findall(r"(content://[^\s\"'}]+)", dump)
    for uri in reversed(found):
        if "intentresolver" in uri or uri.endswith("/"):
            continue
        return uri
    return ""


def _hand_to_saver(package):
    """Give the shared file to DAKA Save when the share list does not show it."""
    if not package:
        return False
    uri = _shared_uri()
    if not uri:
        return False
    result = _adb(
        "shell", "am", "start", "-a", "android.intent.action.SEND", "-t", "*/*",
        "-n", _saver_activity(package),
        "--grant-read-uri-permission",
        "--eu", "android.intent.extra.STREAM", uri,
    )
    return result.returncode == 0 and "Error" not in (result.stdout or "")


def _tap_share(device, label):
    if label and _tap_label(device, label):
        return True
    for word in (label, "DAKA", "DAKA Save"):
        if not word:
            continue
        node = device(textContains=word)
        if node.exists:
            node.click()
            return True
        node = device(descriptionContains=word)
        if node.exists:
            node.click()
            return True
    return False


def _expand_share_sheet(device):
    for label in ("更多", "More", "查看全部", "其他应用", "其他應用程式", "使用其他应用打开"):
        if _tap_label(device, label):
            time.sleep(1)
            return True
    return False


def _save_share(device, label, package=""):
    for _ in range(4):
        _deny_location(device)
        _expand_share_sheet(device)
        deadline = time.time() + 4
        while time.time() < deadline:
            if _tap_share(device, label):
                time.sleep(2)
                if device.app_current().get("package") != "com.android.intentresolver":
                    return
            time.sleep(0.4)
        if _hand_to_saver(package):
            time.sleep(2)
            return
        device.swipe(540, 1600, 540, 800, 0.2)
        time.sleep(0.6)
    if _hand_to_saver(package):
        time.sleep(2)
        return
    raise SystemExit("分享清單沒有 %s。目前畫面：%s" % (label, "、".join(_screen_labels(device))))


_HEADER = {
    "Name": "姓名",
    "Date": "日期",
    "In": "上班",
    "In Place": "上班位置",
    "Out": "下班",
    "Out Place": "下班位置",
}


def _as_payroll_csv(path):
    """English DAKA headers become the Chinese columns the payroll app already reads."""
    import csv
    text = path.read_text(encoding="utf-8-sig")
    rows = list(csv.reader(text.splitlines()))
    if not rows or ("姓名" not in rows[0] and "Name" not in rows[0]):
        raise SystemExit("匯出檔沒有姓名欄。")
    rows[0] = [_HEADER.get(name, name) for name in rows[0]]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(rows)
    return path


def _pull_new(before):
    deadline = time.time() + 25
    picked = ""
    while time.time() < deadline and not picked:
        for name in _downloads():
            if name in before:
                continue
            if name.lower().endswith(".csv") and name.startswith("daka_export_"):
                picked = name
                break
        if not picked:
            time.sleep(1)
    if not picked:
        raise SystemExit("模擬器的 Download 沒有匯出檔。")
    OUTBOX.mkdir(parents=True, exist_ok=True)
    local = OUTBOX / f"pulled_{picked}"
    copied = _adb("pull", f"/sdcard/Download/{picked}", str(local), timeout=60)
    if copied.returncode != 0 or not local.exists():
        raise SystemExit("無法從模擬器取出匯出檔。")
    _adb("shell", "rm", "-f", f"/sdcard/Download/{picked}")
    return local


def _ranges(today):
    start = today.replace(day=1)
    ranges = [(start, today)]
    if today.day <= 5:
        previous = start - timedelta(days=1)
        ranges.append((previous.replace(day=1), previous))
    return ranges


def _grab_open_share(device, plan):
    """The emulator sometimes restarts with the share sheet still open."""
    label = plan.get("save_label") or ""
    if not (device(text="Sharing 1 file").exists or (label and device(text=label).exists)):
        return None
    before = set(_downloads())
    _save_share(device, label, plan.get("save_package") or "")
    time.sleep(2)
    try:
        return _as_payroll_csv(_pull_new(before))
    except SystemExit:
        return None


def _forget_old_exports(keep):
    """Leave only the files from this run. Older exports are already merged or replaced."""
    if not OUTBOX.exists():
        return
    kept = set(keep)
    for path in OUTBOX.glob("daka_*.csv"):
        if path.name not in kept:
            path.unlink(missing_ok=True)
    for path in OUTBOX.glob("pulled_*"):
        path.unlink(missing_ok=True)


def _export(device, plan, today):
    saved = []
    package = plan["package"]
    device.app_start(package)
    time.sleep(3)
    shared = _grab_open_share(device, plan)
    if shared is not None:
        named = OUTBOX / f"daka_share_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        shutil.move(str(shared), named)
        saved.append(named.name)
    try:
        saved.extend(_export_ranges(device, plan, today))
    except SystemExit:
        if not saved:
            raise
    if saved:
        _forget_old_exports(saved)
    return saved


def _export_ranges(device, plan, today):
    saved = []
    package = plan["package"]
    for start, end in _ranges(today):
        _quiet_location(package)
        _adb("shell", "am", "force-stop", "com.android.intentresolver")
        device.app_start(package)
        time.sleep(4)
        _deny_location(device)
        if _logged_out(device, plan.get("logged_out")):
            raise SystemExit(LOGGED_OUT)
        opened = _open_export(device, plan)
        if isinstance(opened, Path):
            named = OUTBOX / f"daka_share_{time.strftime('%Y%m%d_%H%M%S')}.csv"
            shutil.move(str(opened), named)
            saved.append(named.name)
            continue
        _deny_location(device)
        tab = device(text=plan["tab"])
        if tab.exists:
            tab.click()
            time.sleep(0.5)
        _set_date(device, plan["start"], start)
        _set_date(device, plan["end"], end)
        before = set(_downloads())
        tapped = False
        for label in _export_actions(plan):
            if _tap_label(device, label):
                tapped = True
                break
        if not tapped:
            raise SystemExit("畫面上找不到匯出。目前畫面：%s" % "、".join(_screen_labels(device)))
        time.sleep(2)
        _save_share(device, plan["save_label"], plan.get("save_package") or "")
        time.sleep(2)
        pulled = _as_payroll_csv(_pull_new(before))
        named = OUTBOX / f"daka_{start.isoformat()}_{end.isoformat()}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        shutil.move(str(pulled), named)
        saved.append(named.name)
        _adb("shell", "input", "keyevent", "4")
        time.sleep(1)
    return saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="boot, app, and login only")
    args = parser.parse_args()
    plan = _steps()
    if not plan.get("package") or not plan.get("save_label"):
        return _status(False, "尚未校準 DAKA 畫面，請先做一次校準。")
    if shutil.which("adb") is None:
        return _status(False, "這部電腦沒有 adb。")
    if not _boot():
        return _status(False, "模擬器沒有啟動。")
    listed = _adb("shell", "pm", "path", plan["package"])
    if listed.returncode != 0 or "package:" not in (listed.stdout or ""):
        return _status(False, "模擬器未安裝 DAKA。")
    saver = _adb("shell", "pm", "path", plan.get("save_package", ""))
    if saver.returncode != 0 or "package:" not in (saver.stdout or ""):
        apk = ROOT / "saver" / "build" / "aligned.apk"
        if apk.exists():
            installed = _adb("install", "-r", str(apk), timeout=60)
            saver = _adb("shell", "pm", "path", plan.get("save_package", ""))
            if installed.returncode != 0:
                saver = installed
        if saver.returncode != 0 or "package:" not in (getattr(saver, "stdout", "") or ""):
            return _status(False, "模擬器未安裝 DAKA Save。")
    device = _device()
    if device is None:
        return _status(False, "未安裝 uiautomator2。")
    _quiet_location(plan["package"])
    device.app_start(plan["package"])
    time.sleep(3)
    _deny_location(device)
    if _logged_out(device, plan.get("logged_out")):
        return _status(False, LOGGED_OUT)
    if args.check:
        return _status(True, "DAKA 已登入。")
    try:
        files = _export(device, plan, date.today())
    except SystemExit as error:
        return _status(False, str(error))
    return _status(True, "已匯出。", files)


if __name__ == "__main__":
    sys.exit(main())
