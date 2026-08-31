"""Launch Windows meeting captions with newest history entries at the top.

This wrapper keeps Hayamimi's general multilingual pipeline unchanged while
applying meeting-only presentation and audio-input tuning:
  * newest finalized history stays directly below the live area
  * live words must survive three partial hypotheses and the newest two words
    remain withheld until they move deeper into the stable prefix
  * Windows playback audio is streaming-resampled to 16 kHz with soxr MQ
"""

from __future__ import annotations

import numpy as np
import soxr

import meeting_captions
import subtitle_server
import meeting_captions_buffered as buffered


_MEETING_RESAMPLERS: dict[tuple[int, int], soxr.ResampleStream] = {}


def _meeting_resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Meeting-only streaming resampler; ASR output rate remains unchanged."""
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    if src_rate == dst_rate:
        return samples
    key = (src_rate, dst_rate)
    stream = _MEETING_RESAMPLERS.get(key)
    if stream is None:
        stream = soxr.ResampleStream(
            src_rate,
            dst_rate,
            1,
            dtype="float32",
            quality="MQ",
        )
        _MEETING_RESAMPLERS[key] = stream
    return np.asarray(stream.resample_chunk(samples, last=False), dtype=np.float32)


def _patch_live_stability_html(html: str) -> str:
    replacements = [
        (
            "  let previousPartialWords = [];",
            "  let partialWordHistory = [];",
        ),
        (
            "  const LIVE_ANCHOR_WORDS = 8;\n"
            "  const WORD_REVEAL_MS = 55;",
            "  const LIVE_ANCHOR_WORDS = 8;\n"
            "  const LIVE_STABILITY_PARTIALS = 3;\n"
            "  const LIVE_HOLD_WORDS = 2;\n"
            "  const WORD_REVEAL_MS = 55;",
        ),
        (
            "  function acceptPartial(text) {\n"
            "    const words = tokenizeWords(text);\n"
            "    if (!words.length) {\n"
            "      previousPartialWords = [];\n"
            "      return;\n"
            "    }\n"
            "    if (!previousPartialWords.length) {\n"
            "      previousPartialWords = words;\n"
            "      return;\n"
            "    }\n\n"
            "    const stableLimit = commonPrefixLength(previousPartialWords, words);\n"
            "    const start = stableContinuationIndex(words, stableLimit);\n"
            "    if (start !== null && stableLimit > start) {\n"
            "      queueStableWords(words.slice(start, stableLimit));\n"
            "    }\n"
            "    previousPartialWords = words;\n"
            "  }",
            "  function stablePrefixAcrossHistory(history) {\n"
            "    if (history.length < LIVE_STABILITY_PARTIALS) return 0;\n"
            "    let limit = history[0].length;\n"
            "    for (let i = 1; i < history.length; i += 1) {\n"
            "      limit = Math.min(limit, commonPrefixLength(history[i - 1], history[i]));\n"
            "      if (!limit) break;\n"
            "    }\n"
            "    return limit;\n"
            "  }\n\n"
            "  function acceptPartial(text) {\n"
            "    const words = tokenizeWords(text);\n"
            "    if (!words.length) {\n"
            "      partialWordHistory = [];\n"
            "      return;\n"
            "    }\n"
            "    partialWordHistory.push(words);\n"
            "    if (partialWordHistory.length > LIVE_STABILITY_PARTIALS) partialWordHistory.shift();\n"
            "    if (partialWordHistory.length < LIVE_STABILITY_PARTIALS) return;\n\n"
            "    const stableLimit = stablePrefixAcrossHistory(partialWordHistory);\n"
            "    const displayLimit = Math.max(0, stableLimit - LIVE_HOLD_WORDS);\n"
            "    const start = stableContinuationIndex(words, displayLimit);\n"
            "    if (start !== null && displayLimit > start) {\n"
            "      queueStableWords(words.slice(start, displayLimit));\n"
            "    }\n"
            "  }",
        ),
        (
            "    previousPartialWords = [];\n"
            "    displayedWords = [];",
            "    partialWordHistory = [];\n"
            "    displayedWords = [];",
        ),
    ]
    for old, new in replacements:
        if old not in html:
            raise RuntimeError(f"meeting live-stability patch target not found: {old[:60]!r}")
        html = html.replace(old, new, 1)
    return html


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


meeting_captions.resample_linear = _meeting_resample
buffered.MEETING_DASHBOARD_HTML = _patch_dashboard_html(
    _patch_live_stability_html(buffered.MEETING_DASHBOARD_HTML)
)
subtitle_server.DASHBOARD_HTML = buffered.MEETING_DASHBOARD_HTML


if __name__ == "__main__":
    raise SystemExit(buffered.main())
