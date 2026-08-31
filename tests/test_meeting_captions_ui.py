import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _string_constant(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def test_live_caption_words_are_appended_without_rewriting_existing_nodes():
    html = _string_constant(
        ROOT / "scripts" / "meeting_captions_buffered.py",
        "MEETING_DASHBOARD_HTML",
    )

    assert ".word { display:inline-block; white-space:nowrap; }" in html
    assert "function appendWordNode(container, word)" in html
    assert "container.appendChild(span);" in html
    assert "function appendStableWord(word)" in html
    assert "displayedWords.push(word);" in html


def test_live_caption_only_commits_words_stable_across_partial_hypotheses():
    html = _string_constant(
        ROOT / "scripts" / "meeting_captions_buffered.py",
        "MEETING_DASHBOARD_HTML",
    )

    assert "function commonPrefixLength(a, b)" in html
    assert "const stableLimit = commonPrefixLength(previousPartialWords, words);" in html
    assert "function stableContinuationIndex(words, limit)" in html
    assert "const locked = lockedWords();" in html
    assert "queueStableWords(words.slice(start, stableLimit));" in html


def test_live_caption_reveals_new_words_progressively():
    html = _string_constant(
        ROOT / "scripts" / "meeting_captions_buffered.py",
        "MEETING_DASHBOARD_HTML",
    )

    assert "const WORD_REVEAL_MS = 55;" in html
    assert "function drainWordQueue()" in html
    assert "appendStableWord(pendingWords.shift());" in html
    assert "setTimeout(() =>" in html


def test_finalization_promotes_streamed_rows_without_replacing_their_text():
    html = _string_constant(
        ROOT / "scripts" / "meeting_captions_buffered.py",
        "MEETING_DASHBOARD_HTML",
    )

    assert "function finalizeLiveRows(text)" in html
    assert "row.classList.remove('speculative');" in html
    assert "row.classList.add('final');" in html
    assert "appendFinalRemainder(text);" in html
    finalize_body = html.split("function finalizeLiveRows(text)", 1)[1].split("function addFinal(text)", 1)[0]
    assert ".textContent = text" not in finalize_body


def test_speculative_mode_is_default_and_copy_all_uses_only_finals():
    html = _string_constant(
        ROOT / "scripts" / "meeting_captions_buffered.py",
        "MEETING_DASHBOARD_HTML",
    )

    assert "localStorage.getItem('hayamimi-speculative') !== 'off'" in html
    assert "querySelectorAll('.line.final .text')" in html


def test_meeting_caption_display_chunks_long_utterances():
    html = _string_constant(
        ROOT / "scripts" / "meeting_captions_buffered.py",
        "MEETING_DASHBOARD_HTML",
    )

    assert "const CAPTION_MAX_WORDS = 24;" in html
    assert "const CAPTION_MAX_CHARS = 160;" in html
    assert "function sentenceUnits(text)" in html
    assert "new Intl.Segmenter('en', {granularity:'sentence'})" in html
    assert "function splitLongCaption(text)" in html
    assert "function splitCaptionText(text)" in html
    assert '<span class="count"><span id="count">0</span> 字幕</span>' in html


def test_windows_meeting_vad_defaults_to_200ms_silence():
    source = (ROOT / "scripts" / "meeting_captions.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--min-silence", type=float, default=0.20,' in source
