# Windows meeting captions

This adds a private system-audio mode for English online meetings without integrating with Teams, Zoom, Meet, Webex, or the meeting host.

## Use

On Windows, double-click:

`meeting_captions.bat`

On the first run it creates `.venv`, installs only the dependencies needed for meeting captions, downloads the English ASR models, then launches the local Hayamimi dashboard. Later runs go directly to captions.

The default Windows playback device is captured through WASAPI loopback. You can keep listening normally through headphones or speakers.

If the meeting application is configured to use a different output device, run:

```bat
.venv\Scripts\python scripts\meeting_captions.py --list-devices
.venv\Scripts\python scripts\meeting_captions.py --device 12
```

## Defaults

- English is forced, so no per-utterance language switching is needed.
- English ASR uses Hayamimi's Parakeet TDT 0.6B v3 route.
- The existing browser dashboard opens automatically at `http://localhost:8833/dashboard`.
- No meeting bot joins the call.
- Audio stays local to Hayamimi's normal CPU-only pipeline.
- Transcripts are not written to disk unless `--transcript PATH` is supplied.

## Notes

System audio capture currently targets Windows because it uses WASAPI loopback via PyAudioWPatch. The callback path synthesizes silence if Windows stops sending loopback packets while idle, so Hayamimi's VAD can still finalize the previous sentence promptly.
