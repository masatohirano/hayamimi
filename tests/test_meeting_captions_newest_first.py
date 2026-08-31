import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_patch_function(name: str):
    path = ROOT / "scripts" / "meeting_captions_newest_first.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.Module(body=[fn], type_ignores=[])
    namespace = {}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


def test_newest_first_patch_moves_follow_anchor_to_top_and_prepends_rows():
    patch = _load_patch_function("_patch_dashboard_html")
    source = """  function nearBottom() {
    return historyBox.scrollHeight - historyBox.scrollTop - historyBox.clientHeight < 90;
  }
  function goLatest() {
    historyBox.scrollTop = historyBox.scrollHeight;
  }
  follow = nearBottom();
    if (before && before.isConnected) historyBox.insertBefore(row, before);
    else historyBox.appendChild(row);
      finals[0].remove();
      for (const block of blocks) makeRow(block, 'final', stamp);
"""
    out = patch(source)
    assert "function nearTop()" in out
    assert "follow = nearTop();" in out
    assert "historyBox.scrollTop = 0;" in out
    assert "historyBox.prepend(row);" in out
    assert "finals[finals.length - 1].remove();" in out
    assert "for (const block of [...blocks].reverse())" in out


def test_live_stability_patch_requires_three_partials_and_holds_two_words():
    patch = _load_patch_function("_patch_live_stability_html")
    source = """  let previousPartialWords = [];
  const LIVE_ANCHOR_WORDS = 8;
  const WORD_REVEAL_MS = 55;
  function acceptPartial(text) {
    const words = tokenizeWords(text);
    if (!words.length) {
      previousPartialWords = [];
      return;
    }
    if (!previousPartialWords.length) {
      previousPartialWords = words;
      return;
    }

    const stableLimit = commonPrefixLength(previousPartialWords, words);
    const start = stableContinuationIndex(words, stableLimit);
    if (start !== null && stableLimit > start) {
      queueStableWords(words.slice(start, stableLimit));
    }
    previousPartialWords = words;
  }
    previousPartialWords = [];
    displayedWords = [];
"""
    out = patch(source)
    assert "let partialWordHistory = [];" in out
    assert "const LIVE_STABILITY_PARTIALS = 3;" in out
    assert "const LIVE_HOLD_WORDS = 2;" in out
    assert "function stablePrefixAcrossHistory(history)" in out
    assert "partialWordHistory.length < LIVE_STABILITY_PARTIALS" in out
    assert "const displayLimit = Math.max(0, stableLimit - LIVE_HOLD_WORDS);" in out
    assert "queueStableWords(words.slice(start, displayLimit));" in out
    assert "previousPartialWords" not in out


def test_meeting_wrapper_uses_stateful_soxr_without_changing_general_resampler():
    wrapper = (ROOT / "scripts" / "meeting_captions_newest_first.py").read_text(encoding="utf-8")
    audio_utils = (ROOT / "scripts" / "audio_utils.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-meeting.txt").read_text(encoding="utf-8")
    batch = (ROOT / "meeting_captions.bat").read_text(encoding="utf-8")

    assert "soxr.ResampleStream(" in wrapper
    assert 'quality="MQ"' in wrapper
    assert "resample_chunk(samples, last=False)" in wrapper
    assert "meeting_captions.resample_linear = _meeting_resample" in wrapper
    assert "def resample_linear(" in audio_utils
    assert "soxr" not in audio_utils
    assert "soxr>=0.3.7,<2" in requirements
    assert "pyaudiowpatch, soxr" in batch


def test_default_windows_launcher_uses_newest_first_dashboard():
    batch = (ROOT / "meeting_captions.bat").read_text(encoding="utf-8")
    assert "scripts\\meeting_captions_newest_first.py" in batch
