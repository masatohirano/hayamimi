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


def test_speculative_caption_promotes_the_same_history_row():
    html = _string_constant(
        ROOT / "scripts" / "meeting_captions_buffered.py",
        "MEETING_DASHBOARD_HTML",
    )

    assert "speculativeRow = makeRow(clean, 'speculative');" in html
    assert "let row = speculativeRow && speculativeRow.isConnected ? speculativeRow : null;" in html
    assert "row.classList.remove('speculative');" in html
    assert "row.classList.add('final');" in html
    assert "row.querySelector('.text').textContent = text;" in html


def test_speculative_mode_is_default_and_copy_all_uses_only_finals():
    html = _string_constant(
        ROOT / "scripts" / "meeting_captions_buffered.py",
        "MEETING_DASHBOARD_HTML",
    )

    assert "localStorage.getItem('hayamimi-speculative') !== 'off'" in html
    assert "querySelectorAll('.line.final .text')" in html


def test_windows_meeting_vad_defaults_to_200ms_silence():
    source = (ROOT / "scripts" / "meeting_captions.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--min-silence", type=float, default=0.20,' in source
