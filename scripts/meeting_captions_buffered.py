"""Meeting-focused Hayamimi UI with a persistent, scrollable final-caption buffer."""

import json
import queue

import subtitle_server


MEETING_DASHBOARD_HTML = r"""<!doctype html>
<html lang="ja">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>hayamimi meeting captions</title>
<style>
  :root { color-scheme:dark; --bg:#101114; --panel:#17191e; --line:#2a2d34;
          --text:#f3f3f1; --muted:#999da7; }
  * { box-sizing:border-box; }
  html,body { height:100%; margin:0; }
  body { background:var(--bg); color:var(--text); font-family:system-ui,-apple-system,
         "Segoe UI",sans-serif; display:flex; flex-direction:column; overflow:hidden; }
  header { flex:none; padding:12px 18px; border-bottom:1px solid var(--line);
           display:flex; align-items:center; gap:12px; }
  header strong { font-size:15px; }
  #status { margin-left:auto; color:var(--muted); font-size:12px; }
  #live { flex:none; background:var(--panel); border-bottom:1px solid var(--line);
          padding:12px 18px 16px; min-height:100px; }
  .label { color:var(--muted); font-size:11px; letter-spacing:.12em; margin-bottom:7px; }
  #partial { font-size:23px; line-height:1.45; min-height:34px; }
  #partial.idle { color:#6d717a; }
  #history-head { flex:none; padding:10px 18px; border-bottom:1px solid var(--line);
                  display:flex; align-items:center; gap:12px; }
  #history-head .count { color:var(--muted); font-size:12px; }
  button { border:1px solid var(--line); background:var(--panel); color:var(--text);
           border-radius:7px; padding:6px 10px; cursor:pointer; }
  #copy-all { margin-left:auto; }
  #history { flex:1; min-height:0; overflow-y:auto; padding:4px 18px 32px;
             scroll-behavior:smooth; }
  .line { display:grid; grid-template-columns:72px minmax(0,1fr); gap:10px;
          padding:10px 0; border-bottom:1px solid #202329; }
  .time { color:var(--muted); font-size:11px; padding-top:3px;
          font-variant-numeric:tabular-nums; }
  .text { font-size:18px; line-height:1.55; user-select:text; }
  #empty { color:#666b74; padding:20px 0; }
  #jump { position:fixed; right:24px; bottom:22px; background:#252a35;
          border-color:#3a4151; box-shadow:0 4px 18px rgba(0,0,0,.35); }
  #jump[hidden] { display:none; }
  @media (max-width:700px) {
    #partial { font-size:19px; } .text { font-size:16px; }
    .line { grid-template-columns:58px minmax(0,1fr); }
  }
</style>
<body>
<header>
  <strong>早耳 Meeting Captions</strong>
  <span id="status">connecting...</span>
</header>
<section id="live">
  <div class="label">LIVE / 発話中</div>
  <div id="partial" class="idle">音声を待っています...</div>
</section>
<div id="history-head">
  <strong>確定済み</strong>
  <span class="count"><span id="count">0</span> 発話</span>
  <button id="copy-all" type="button">全体をコピー</button>
</div>
<main id="history">
  <div id="empty">確定した字幕がここに蓄積されます。</div>
</main>
<button id="jump" type="button" hidden>最新へ</button>
<script>
  const historyBox = document.getElementById('history');
  const partial = document.getElementById('partial');
  const status = document.getElementById('status');
  const countEl = document.getElementById('count');
  const empty = document.getElementById('empty');
  const jump = document.getElementById('jump');
  const copyAll = document.getElementById('copy-all');
  let follow = true, unseen = 0, count = 0;
  const MAX_LINES = 1000;

  function nearBottom() {
    return historyBox.scrollHeight - historyBox.scrollTop - historyBox.clientHeight < 90;
  }
  function goLatest() {
    follow = true; unseen = 0; jump.hidden = true; jump.textContent = '最新へ';
    historyBox.scrollTop = historyBox.scrollHeight;
  }
  historyBox.addEventListener('scroll', () => {
    follow = nearBottom();
    if (follow) { unseen = 0; jump.hidden = true; jump.textContent = '最新へ'; }
  });
  jump.addEventListener('click', goLatest);

  function addFinal(text) {
    if (!text || !text.trim()) return;
    if (empty.isConnected) empty.remove();
    const row = document.createElement('div'); row.className = 'line';
    const tm = document.createElement('div'); tm.className = 'time';
    tm.textContent = new Date().toLocaleTimeString([], {
      hour:'2-digit', minute:'2-digit', second:'2-digit'
    });
    const tx = document.createElement('div'); tx.className = 'text'; tx.textContent = text;
    row.append(tm, tx); historyBox.appendChild(row);
    count += 1; countEl.textContent = count;
    while (historyBox.querySelectorAll('.line').length > MAX_LINES) {
      historyBox.querySelector('.line')?.remove();
    }
    if (follow || nearBottom()) {
      goLatest();
    } else {
      unseen += 1; jump.hidden = false; jump.textContent = `最新へ (${unseen})`;
    }
  }

  copyAll.addEventListener('click', async () => {
    const text = Array.from(historyBox.querySelectorAll('.text'))
      .map(x => x.textContent).join('\n');
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      copyAll.textContent = 'コピーしました';
      setTimeout(() => copyAll.textContent = '全体をコピー', 1200);
    } catch (_) {
      const range = document.createRange(); range.selectNodeContents(historyBox);
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    }
  });

  const es = new EventSource('/events');
  es.onopen = () => { status.textContent = 'connected'; };
  es.onerror = () => { status.textContent = 'reconnecting...'; };
  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === 'partial') {
      partial.classList.remove('idle'); partial.textContent = ev.text || '';
    } else if (ev.type === 'final') {
      partial.classList.add('idle'); partial.textContent = '音声を待っています...';
      addFinal(ev.text);
    }
  };
</script>
</body>
</html>
"""


_BaseSubtitleServer = subtitle_server.SubtitleServer


class BufferedSubtitleServer(_BaseSubtitleServer):
    """Replay recent finalized captions when the meeting page reconnects."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meeting_finals: list[str] = []

    def publish(self, event: dict):
        data = json.dumps(event, ensure_ascii=False)
        with self._lock:
            if event.get("type") == "final":
                self._meeting_finals.append(data)
                del self._meeting_finals[:-1000]
            if event.get("type") == "refine":
                self._refines.append(data)
                del self._refines[:-200]
            for client_q in self._clients:
                client_q.put(data)

    def subscribe(self) -> queue.Queue:
        client_q: queue.Queue = queue.Queue()
        with self._lock:
            for past in self._meeting_finals:
                client_q.put(past)
            for past in self._refines:
                client_q.put(past)
            self._clients.append(client_q)
        return client_q


subtitle_server.DASHBOARD_HTML = MEETING_DASHBOARD_HTML
subtitle_server.SubtitleServer = BufferedSubtitleServer

from meeting_captions import main


if __name__ == "__main__":
    raise SystemExit(main())
