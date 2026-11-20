"""A clock that ticks without rerunning the page. Times are Hong Kong time."""

import streamlit.components.v1 as components


def live_clock():
    components.html(
        """
        <div id="clock" style="font:700 24px/32px 'Noto Sans TC','Microsoft JhengHei',sans-serif;color:#2B2B2B;font-variant-numeric:tabular-nums"></div>
        <script>
        const node = document.getElementById("clock");
        function tick() {
          const now = new Date(new Date().toLocaleString("en-US", {timeZone: "Asia/Hong_Kong"}));
          const weeks = ["日","一","二","三","四","五","六"];
          const p = (n) => String(n).padStart(2, "0");
          node.textContent = now.getFullYear() + "年" + (now.getMonth()+1) + "月" + now.getDate() + "日 星期" + weeks[now.getDay()] + " " + p(now.getHours()) + ":" + p(now.getMinutes()) + ":" + p(now.getSeconds());
        }
        tick();
        setInterval(tick, 1000);
        </script>
        """,
        height=36,
    )
