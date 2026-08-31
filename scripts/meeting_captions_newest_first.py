"""Launch Windows meeting captions with newest history entries at the top.

This keeps the live display at the top of the page and reverses only the
meeting-history insertion/follow behavior. The underlying ASR, VAD, replay
buffer, and append-only word streaming stay unchanged.
"""

from __future__ import annotations

import subtitle_server
import meeting_captions_buffered as buffered


def _patch_dashboard_html(html: str) -> str:
    replacements = [
        (
            "  function nearBottom() {\n"
            "    return historyBox.scrollHeight - historyBox.scrollTop - historyBox.clientHeight < 90;\n"
            "  }",
            "  function nearTop() {\n"
            "    return historyBox.scrollTop < 90;\n"
            "  }",
        ),
        (
            "    if (before && before.isConnected) historyBox.insertBefore(row, before);\n"
            "    else historyBox.appendChild(row);",
            "    if (before && before.isConnected) historyBox.insertBefore(row, before);\n"
            "    else historyBox.prepend(row);",
        ),
        (
            "      finals[0].remove();",
            "      finals[finals.length - 1].remove();",
        ),
        (
            "      for (const block of blocks) makeRow(block, 'final', stamp);",
            "      for (const block of [...blocks].reverse()) makeRow(block, 'final', stamp);",
        ),
    ]
    for old, new in replacements:
        if old not in html:
            raise RuntimeError(f"meeting dashboard patch target not found: {old[:60]!r}")
        html = html.replace(old, new, 1)

    html = html.replace("nearBottom()", "nearTop()")
    html = html.replace("historyBox.scrollTop = historyBox.scrollHeight;", "historyBox.scrollTop = 0;")
    return html


buffered.MEETING_DASHBOARD_HTML = _patch_dashboard_html(buffered.MEETING_DASHBOARD_HTML)
subtitle_server.DASHBOARD_HTML = buffered.MEETING_DASHBOARD_HTML


if __name__ == "__main__":
    raise SystemExit(buffered.main())
