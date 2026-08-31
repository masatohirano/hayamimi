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
  #partial .live-block { display:block; min-height:1.45em; }
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
  .word { display:inline-block; white-space:nowrap; }
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
  let previousPartialWords = [];
  let displayedWords = [];
  let pendingWords = [];
  let wordTimer = null;
  let liveBlocks = [];
  let speculativeEnabled = localStorage.getItem('hayamimi-speculative') !== 'off';
  const MAX_LINES = 1000;
  const CAPTION_MAX_WORDS = 24;
  const CAPTION_MIN_WORDS = 10;
  const CAPTION_MAX_CHARS = 160;
  const LIVE_ANCHOR_WORDS = 8;
  const WORD_REVEAL_MS = 55;

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

  function tokenizeWords(text) {
    const clean = normalizeCaptionText(text);
    return clean ? clean.split(' ') : [];
  }

  function wordKey(word) {
    const lowered = (word || '').toLowerCase();
    const stripped = lowered.replace(/^[^a-z0-9']+|[^a-z0-9']+$/g, '');
    return stripped || lowered;
  }

  function sameWord(a, b) {
    return wordKey(a) === wordKey(b);
  }

  function commonPrefixLength(a, b) {
    const n = Math.min(a.length, b.length);
    let i = 0;
    while (i < n && sameWord(a[i], b[i])) i += 1;
    return i;
  }

  function captionWordCount(text) {
    return tokenizeWords(text).length;
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

      const tail = words.length - end;
      if (tail > 0 && tail < CAPTION_MIN_WORDS && end - start > CAPTION_MIN_WORDS) {
        const giveBack = CAPTION_MIN_WORDS - tail;
        end = Math.max(start + CAPTION_MIN_WORDS, end - giveBack);
      }

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

  function appendWordNode(container, word) {
    if (container.childNodes.length) container.appendChild(document.createTextNode(' '));
    const span = document.createElement('span');
    span.className = 'word';
    span.textContent = word;
    container.appendChild(span);
  }

  function blockNeedsNewRow(block, word) {
    if (!block || block.sealed) return true;
    if (block.words.length >= CAPTION_MAX_WORDS) return true;
    const added = word.length + (block.words.length ? 1 : 0);
    return block.chars + added > CAPTION_MAX_CHARS;
  }

  function sentenceEnds(word) {
    return /[.!?]+["')\]]*$/.test(word);
  }

  function createLiveBlock() {
    const block = {words: [], chars: 0, sealed: false, row: null, panel: null};
    liveBlocks.push(block);
    const panel = document.createElement('span');
    panel.className = 'live-block';
    partial.appendChild(panel);
    block.panel = panel;
    if (speculativeEnabled) block.row = makeRow('', 'speculative');
    return block;
  }

  function ensureHistoryRow(block) {
    if (block.row && block.row.isConnected) return block.row;
    block.row = makeRow('', 'speculative');
    const tx = block.row.querySelector('.text');
    for (const word of block.words) appendWordNode(tx, word);
    return block.row;
  }

  function appendStableWord(word) {
    const shouldFollow = speculativeEnabled && (follow || nearBottom());
    let block = liveBlocks[liveBlocks.length - 1];
    if (blockNeedsNewRow(block, word)) block = createLiveBlock();

    block.words.push(word);
    block.chars += word.length + (block.words.length > 1 ? 1 : 0);
    displayedWords.push(word);
    appendWordNode(block.panel, word);

    if (speculativeEnabled) {
      const row = ensureHistoryRow(block);
      const tx = row.querySelector('.text');
      const rowWords = tx.querySelectorAll('.word').length;
      if (rowWords < block.words.length) appendWordNode(tx, word);
    }

    if (sentenceEnds(word) && block.words.length >= CAPTION_MIN_WORDS) block.sealed = true;
    if (shouldFollow) historyBox.scrollTop = historyBox.scrollHeight;
  }

  function lockedWords() {
    return displayedWords.concat(pendingWords);
  }

  function drainWordQueue() {
    if (wordTimer !== null || !pendingWords.length) return;
    appendStableWord(pendingWords.shift());
    if (pendingWords.length) {
      wordTimer = setTimeout(() => {
        wordTimer = null;
        drainWordQueue();
      }, WORD_REVEAL_MS);
    }
  }

  function queueStableWords(words) {
    if (!words.length) return;
    pendingWords.push(...words);
    drainWordQueue();
  }

  function flushWordQueue() {
    if (wordTimer !== null) {
      clearTimeout(wordTimer);
      wordTimer = null;
    }
    while (pendingWords.length) appendStableWord(pendingWords.shift());
  }

  function stableContinuationIndex(words, limit) {
    const stable = words.slice(0, limit);
    const locked = lockedWords();
    if (!locked.length) return 0;

    if (locked.length <= stable.length) {
      let prefixMatches = true;
      for (let i = 0; i < locked.length; i += 1) {
        if (!sameWord(locked[i], stable[i])) {
          prefixMatches = false;
          break;
        }
      }
      if (prefixMatches) return locked.length;
    }

    const maxAnchor = Math.min(LIVE_ANCHOR_WORDS, locked.length, stable.length);
    for (let len = maxAnchor; len >= 2; len -= 1) {
      const suffix = locked.slice(locked.length - len);
      for (let start = stable.length - len; start >= 0; start -= 1) {
        let matches = true;
        for (let j = 0; j < len; j += 1) {
          if (!sameWord(suffix[j], stable[start + j])) {
            matches = false;
            break;
          }
        }
        if (matches) return start + len;
      }
    }
    return null;
  }

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

  function appendFinalRemainder(text) {
    const words = tokenizeWords(text);
    if (!words.length) return;
    const start = stableContinuationIndex(words, words.length);
    if (start === null) return;
    queueStableWords(words.slice(start));
    flushWordQueue();
  }

  function resetLiveState() {
    previousPartialWords = [];
    displayedWords = [];
    pendingWords = [];
    if (wordTimer !== null) clearTimeout(wordTimer);
    wordTimer = null;
    liveBlocks = [];
    currentPartial = '';
    partial.replaceChildren();
    partial.classList.add('idle');
    partial.textContent = '音声を待っています...';
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

  function finalizeLiveRows(text) {
    appendFinalRemainder(text);
    const stamp = timestamp();
    const rows = [];
    for (const block of liveBlocks) {
      if (!block.words.length) continue;
      const row = speculativeEnabled ? ensureHistoryRow(block) : null;
      if (!row) continue;
      row.classList.remove('speculative');
      row.classList.add('final');
      row.querySelector('.time').textContent = stamp;
      rows.push(row);
    }
    return rows;
  }

  function addFinal(text) {
    const shouldFollow = follow || nearBottom();
    let added = 0;

    if (speculativeEnabled && lockedWords().length) {
      added = finalizeLiveRows(text).length;
    } else {
      const blocks = splitCaptionText(text);
      if (!blocks.length) {
        resetLiveState();
        return;
      }
      const stamp = timestamp();
      for (const block of blocks) makeRow(block, 'final', stamp);
      added = blocks.length;
    }

    resetLiveState();
    trimFinals();
    if (shouldFollow) {
      goLatest();
    } else if (added) {
      unseen += added;
      jump.hidden = false;
      jump.textContent = `最新へ (${unseen})`;
    }
  }

  function updatePartialDisplay(text) {
    currentPartial = text || '';
    if (currentPartial.trim()) {
      if (partial.classList.contains('idle')) {
        partial.classList.remove('idle');
        partial.replaceChildren();
      }
      acceptPartial(currentPartial);
    }
  }

  function rebuildSpeculativeRows() {
    for (const block of liveBlocks) ensureHistoryRow(block);
  }

  function removeSpeculativeRows() {
    for (const block of liveBlocks) {
      if (block.row?.isConnected) block.row.remove();
      block.row = null;
    }
    ensureEmpty();
  }

  function applySpeculativeMode() {
    live.hidden = speculativeEnabled;
    speculativeToggle.textContent = `speculative: ${speculativeEnabled ? 'ON' : 'OFF'}`;
    speculativeToggle.setAttribute('aria-pressed', speculativeEnabled ? 'true' : 'false');
    if (speculativeEnabled) rebuildSpeculativeRows();
    else removeSpeculativeRows();
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
    historyBox.querySelectorAll('.line').forEach(x => x.remove());
    resetLiveState();
    count = 0; countEl.textContent = '0'; unseen = 0; follow = true;
    jump.hidden = true; jump.textContent = '最新へ'; ensureEmpty();
  };
  es.onerror = () => { status.textContent = 'reconnecting...'; };
  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === 'partial') {
      updatePartialDisplay(ev.text || '');
    } else if (ev.type === 'final') {
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
