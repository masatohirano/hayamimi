# Windows meeting captions

This adds a private system-audio mode for English online meetings without integrating with Teams, Zoom, Meet, Webex, or the meeting host.

## Use

On Windows, double-click:

`meeting_captions.bat`

On the first run it creates `.venv`, installs only the dependencies needed for meeting captions, downloads the English ASR models, then launches the local Hayamimi dashboard. Later runs go directly to captions.

The default Windows playback device is captured through WASAPI loopback. You can keep listening normally through headphones or speakers.

If the meeting application is configured to use a different output device, run:

```bat
.venv\Scripts\python scripts\meeting_captions_newest_first.py --list-devices
.venv\Scripts\python scripts\meeting_captions_newest_first.py --device 12
```

## Defaults

- English is forced, so no per-utterance language switching is needed.
- English ASR uses Hayamimi's Parakeet TDT 0.6B v3 route.
- VAD finalizes after 0.35 seconds of silence by default.
- Partial ASR hypotheses update every 0.30 seconds in meeting mode by default. Use `--partial-every SEC` to tune it; the general Hayamimi pipeline keeps its 0.5-second default.
- A meeting-focused browser dashboard opens automatically at `http://localhost:8833/dashboard`.
- Speculative captions are enabled by default.
- Live captions use an append-only word stream. A word is eligible for display only after it survives three consecutive partial hypotheses, and the newest two words of that stable prefix remain withheld. This reduces the chance that a transient partial-ASR error becomes permanently locked on screen.
- Newly eligible words are still revealed one by one at a short interval, similar to video captions. Already displayed word nodes are never rewritten or moved by later ASR revisions.
- If a later partial revises earlier speech, the live display keeps the already-read words in place and resumes from a matching recent word sequence when possible instead of replacing the whole caption.
- Live blocks grow only forward. A new block starts at a sentence boundary when practical, or at the existing 24-word / 160-character display limit. This avoids recomputing earlier line breaks while speech is still in progress.
- On finalization, withheld and remaining final words are appended when they align with the live stream, and the same streamed rows are promoted from speculative to finalized without rewriting their text. Short utterances that never produced stable partial words still use the normal sentence-aware final splitter.
- The `speculative: ON/OFF` button switches between the history-integrated live stream and the separate Live area. The preference is retained in the browser.
- Finalized-caption history is newest-first, so the latest confirmed caption stays directly below the live area instead of accumulating at the bottom. If you scroll down to reread older captions, new captions do not pull you back; `最新へ` returns to the top.
- The browser keeps up to 1000 finalized display blocks. The server retains up to 1000 final utterance events and replays them if the browser reconnects or refreshes during the session.
- Finalized lines can be selected and copied individually, and the `全体をコピー` button copies only finalized captions.
- Windows playback audio is downmixed to mono and, when its sample rate differs from 16 kHz, converted with a stateful soxr `MQ` streaming resampler. The ASR still receives the same 16 kHz mono data rate as before.
- No meeting bot joins the call.
- Audio stays local to Hayamimi's normal CPU-only pipeline.
- Transcripts are not written to disk unless `--transcript PATH` is supplied.

## Notes

System audio capture currently targets Windows because it uses WASAPI loopback via PyAudioWPatch. The callback path synthesizes silence if Windows stops sending loopback packets while idle, so Hayamimi's VAD can still finalize the previous sentence promptly.

The soxr change is meeting-only. The general Hayamimi resampling helper remains unchanged, so this tuning cannot alter the existing Japanese or multilingual paths.
