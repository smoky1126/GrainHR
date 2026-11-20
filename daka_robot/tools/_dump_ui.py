"""Print the visible labels on the current emulator screen."""

import re

import uiautomator2 as u2

device = u2.connect()
print("current", device.app_current())
xml = device.dump_hierarchy()
with open("/tmp/daka_ui.xml", "w", encoding="utf-8") as handle:
    handle.write(xml)
for node in re.findall(r"<node [^>]+>", xml):
    clickable = 'clickable="true"' in node
    text = re.search(r'text="([^"]*)"', node)
    desc = re.search(r'content-desc="([^"]*)"', node)
    rid = re.search(r'resource-id="([^"]*)"', node)
    bounds = re.search(r'bounds="([^"]+)"', node)
    label = (text.group(1) if text else "").strip()
    hint = (desc.group(1) if desc else "").strip()
    name = (rid.group(1) if rid else "").strip()
    if not (clickable or hint or (name and "dakaclock" in name)):
        continue
    if not (label or hint or name):
        continue
    print(f"click={clickable} text={label!r} desc={hint!r} id={name} {bounds.group(1) if bounds else ''}")
