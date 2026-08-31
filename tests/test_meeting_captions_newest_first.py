import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_patch_function():
    path = ROOT / "scripts" / "meeting_captions_newest_first.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_patch_dashboard_html"
    )
    module = ast.Module(body=[fn], type_ignores=[])
    namespace = {}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["_patch_dashboard_html"]


def test_newest_first_patch_moves_follow_anchor_to_top_and_prepends_rows():
    patch = _load_patch_function()
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


def test_default_windows_launcher_uses_newest_first_dashboard():
    batch = (ROOT / "meeting_captions.bat").read_text(encoding="utf-8")
    assert "scripts\\meeting_captions_newest_first.py" in batch
