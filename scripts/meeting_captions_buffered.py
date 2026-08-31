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
  #speculative-toggle { font-size:12px; padding:5px 9px; }
  #live { flex:none; background:var(--panel); border-bottom:1px solid var(--line);
          padding:12px 18px 16px; min-height:100px; }
  #live[hidden] { display:none; }
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
  .line.speculative { opacity:.70; }
  .line.speculative .time::after { content:' ~'; }
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
  <button id="speculative-toggle" type="button" aria-pressed="true">speculative: ON</button>
  <span id="status">connecting...</span>
</header>
<section id="live">
  <div class="label">LIVE / 発話中</div>
  <div id="partial" class="idle">音声を待っています...</div>
</section>
<div id="history-head">
  <strong>確定済み</strong>
  <span class="count"><span id="count">0</span> 字幕</span>
  <button id="copy-all" type="button">全体をコピー</button>
</div>
<main id="history">
  <div id="empty">確定した字幕がここに蓄積されます。</div>
</main>
<button id="jump" type="button" hidden>最新へ</button>
<script>
  const historyBox = document.getElementById('history');
  const live = document.getElementById('live');
  const partial = document.getElementById('partial');
  const status = document.getElementById('status');
  const countEl = document.getElementById('count');
  const empty = document.getElementById('empty');
  const jump = document.getElementById('jump');
  const copyAll = document.getElementById('copy-all');
  const speculativeToggle = document.getElementById('speculative-toggle');
  let follow = true, unseen = 0, count = 0, currentPartial = '';
  let speculativeRow = null;
  let speculativeEnabled = localStorage.getItem('hayamimi-speculative') !== 'off';
  const MAX_LINES = 1000;
  const CAPTION_MAX_WORDS = 24;
  const CAPTION_MIN_WORDS = 10;
  const CAPTION_MAX_CHARS = 160;

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

  function timestamp() {
    return new Date().toLocaleTimeString([], {
      hour:'2-digit', minute:'2-digit', second:'2-digit'
    });
  }

  function normalizeCaptionText(text) {
    return (text || '').replace(/\s+/g, ' ').trim();
  }

  function captionWordCount(text) {
    const clean = normalizeCaptionText(text);
    return clean ? clean.split(' ').length : 0;
  }

  function fitsCaption(text) {
    const clean = normalizeCaptionText(text);
    return captionWordCount(clean) <= CAPTION_MAX_WORDS && clean.length <= CAPTION_MAX_CHARS;
  }

  function splitLongCaption(text) {
    const clean = normalizeCaptionText(text);
    if (!clean) return [];
    const words = clean.split(' ');
    const chunks = [];
    let start = 0;

    while (start < words.length) {
      let end = start;
      let chars = 0;
      while (end < words.length && end - start < CAPTION_MAX_WORDS) {
        const added = words[end].length + (end > start ? 1 : 0);
        if (end > start && chars + added > CAPTION_MAX_CHARS) break;
        chars += added;
        end += 1;
      }
      if (end === start) end += 1;

      // Avoid an awkward 24-word block followed by a one- or two-word tail.
      const tail = words.length - end;
      if (tail > 0 && tail < CAPTION_MIN_WORDS && end - start > CAPTION_MIN_WORDS) {
        const giveBack = CAPTION_MIN_WORDS - tail;
        end = Math.max(start + CAPTION_MIN_WORDS, end - giveBack);
      }

      // Prefer a nearby clause boundary without creating a tiny block.
      if (end < words.length && end - start > CAPTION_MIN_WORDS) {
        for (let i = end; i > start + CAPTION_MIN_WORDS; i -= 1) {
          if (/[,;:]$/.test(words[i - 1])) {
            end = i;
            break;
          }
        }
      }

      chunks.push(words.slice(start, end).join(' '));
      start = end;
    }
    return chunks;
  }

  function sentenceUnits(text) {
    const clean = normalizeCaptionText(text);
    if (!clean) return [];
    if (typeof Intl !== 'undefined' && Intl.Segmenter) {
      try {
        const segmenter = new Intl.Segmenter('en', {granularity:'sentence'});
        const units = Array.from(segmenter.segment(clean), x => x.segment.trim()).filter(Boolean);
        if (units.length) return units;
      } catch (_) {}
    }
    const fallback = clean.match(/[^.!?]+(?:[.!?]+(?:["')\]]+)?(?=\s|$)|$)/g);
    return fallback ? fallback.map(x => x.trim()).filter(Boolean) : [clean];
  }

  function splitCaptionText(text) {
    const blocks = [];
    let current = '';
    const flush = () => {
      if (current) blocks.push(current);
      current = '';
    };

    for (const unit of sentenceUnits(text)) {
      if (!fitsCaption(unit)) {
        flush();
        blocks.push(...splitLongCaption(unit));
        continue;
      }
      const joined = current ? `${current} ${unit}` : unit;
      if (current && !fitsCaption(joined)) {
        flush();
        current = unit;
      } else {
        current = joined;
      }
    }
    flush();
    return blocks;
  }

  function currentCaptionBlock(text) {
    const blocks = splitCaptionText(text);
    return blocks.length ? blocks[blocks.length - 1] : '';
  }

  function ensureEmpty() {
    if (count === 0 && !historyBox.querySelector('.line') && !empty.isConnected) {
      historyBox.appendChild(empty);
    }
  }

  function makeRow(text, kind, stamp = timestamp(), before = null) {
    if (empty.isConnected) empty.remove();
    const row = document.createElement('div'); row.className = `line ${kind}`;
    const tm = document.createElement('div'); tm.className = 'time'; tm.textContent = stamp;
    const tx = document.createElement('div'); tx.className = 'text'; tx.textContent = text;
    row.append(tm, tx);
    if (before && before.isConnected) historyBox.insertBefore(row, before);
    else historyBox.appendChild(row);
    return row;
  }

  function promoteRow(row, text, stamp) {
    row.classList.remove('speculative');
    row.classList.add('final');
    row.querySelector('.text').textContent = text;
    row.querySelector('.time').textContent = stamp;
  }

  function trimFinals() {
    let finals = historyBox.querySelectorAll('.line.final');
    while (finals.length > MAX_LINES) {
      finals[0].remove();
      finals = historyBox.querySelectorAll('.line.final');
    }
    count = finals.length;
    countEl.textContent = count;
  }

  function showSpeculative(text) {
    if (!speculativeEnabled) return;
    const clean = currentCaptionBlock(text);
    if (!clean) {
      if (speculativeRow?.isConnected) speculativeRow.remove();
      speculativeRow = null;
      ensureEmpty();
      return;
    }
    const shouldFollow = follow || nearBottom();
    if (!speculativeRow || !speculativeRow.isConnected) {
      speculativeRow = makeRow(clean, 'speculative');
    } else {
      speculativeRow.querySelector('.text').textContent = clean;
    }
    if (shouldFollow) goLatest();
  }

  function addFinal(text) {
    const blocks = splitCaptionText(text);
    if (!blocks.length) return;
    const shouldFollow = follow || nearBottom();
    const stamp = timestamp();
    let row = speculativeRow && speculativeRow.isConnected ? speculativeRow : null;

    if (row) {
      // The speculative row represents the current tail of the utterance. Put
      // earlier finalized blocks immediately before it, then promote that same
      // bottom row to the final tail so text does not jump back to sentence 1.
      for (const block of blocks.slice(0, -1)) {
        makeRow(block, 'final', stamp, row);
      }
      promoteRow(row, blocks[blocks.length - 1], stamp);
      speculativeRow = null;
    } else {
      for (const block of blocks) makeRow(block, 'final', stamp);
    }

    trimFinals();
    if (shouldFollow) {
      goLatest();
    } else {
      unseen += blocks.length;
      jump.hidden = false;
      jump.textContent = `最新へ (${unseen})`;
    }
  }

  function updatePartialDisplay(text) {
    currentPartial = text || '';
    if (currentPartial.trim()) {
      partial.classList.remove('idle'); partial.textContent = currentPartial;
    } else {
      partial.classList.add('idle'); partial.textContent = '音声を待っています...';
    }
    showSpeculative(currentPartial);
  }

  function applySpeculativeMode() {
    live.hidden = speculativeEnabled;
    speculativeToggle.textContent = `speculative: ${speculativeEnabled ? 'ON' : 'OFF'}`;
    speculativeToggle.setAttribute('aria-pressed', speculativeEnabled ? 'true' : 'false');
    if (speculativeEnabled) {
      showSpeculative(currentPartial);
    } else if (speculativeRow?.isConnected) {
      speculativeRow.remove();
      speculativeRow = null;
      ensureEmpty();
    }
  }

  speculativeToggle.addEventListener('click', () => {
    speculativeEnabled = !speculativeEnabled;
    localStorage.setItem('hayamimi-speculative', speculativeEnabled ? 'on' : 'off');
    applySpeculativeMode();
  });

  copyAll.addEventListener('click', async () => {
    const text = Array.from(historyBox.querySelectorAll('.line.final .text'))
      .map(x => x.textContent).join('\n');
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      copyAll.textContent = 'コピーしました';
      setTimeout(() => copyAll.textContent = '全体をコピー', 1200);
    } catch (_) {
      const finalized = historyBox.querySelectorAll('.line.final');
      if (!finalized.length) return;
      const range = document.createRange();
      range.setStartBefore(finalized[0]);
      range.setEndAfter(finalized[finalized.length - 1]);
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    }
  });

  applySpeculativeMode();

  const es = new EventSource('/events');
  es.onopen = () => {
    status.textContent = 'connected';
    // The server replays the finalized buffer on every SSE reconnect. Clear
    // rendered rows first so a transient reconnect never duplicates captions.
    historyBox.querySelectorAll('.line').forEach(x => x.remove());
    speculativeRow = null; currentPartial = '';
    partial.classList.add('idle'); partial.textContent = '音声を待っています...';
    count = 0; countEl.textContent = '0'; unseen = 0; follow = true;
    jump.hidden = true; jump.textContent = '最新へ'; ensureEmpty();
  };
  es.onerror = () => { status.textContent = 'reconnecting...'; };
  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === 'partial') {
      updatePartialDisplay(ev.text || '');
    } else if (ev.type === 'final') {
      currentPartial = '';
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
