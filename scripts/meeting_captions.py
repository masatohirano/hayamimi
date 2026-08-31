r"""Private, bot-free English captions for Windows online meetings.

Captures the audio that Windows is sending to the current output device via
WASAPI loopback, while the user keeps listening normally through speakers or
headphones. The meeting platform is not integrated with or notified.

Typical use is the repository-root `meeting_captions.bat` launcher. Manual:

    .venv\Scripts\python scripts\meeting_captions.py

By default it:
  * captures the default Windows output device
  * forces English recognition with Parakeet TDT 0.6B v3
  * starts hayamimi's dashboard on http://localhost:8833/dashboard
  * opens that dashboard in the default browser

Use --list-devices when the meeting app is playing to a non-default output.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
import webbrowser

import numpy as np

from asr_engine import RoutedASR
from audio_utils import decode_pcm16, resample_linear
from realtime_transcribe import (
    AudioHistory,
    PartialPrinter,
    Refiner,
    SAMPLE_RATE,
    SessionStats,
    WINDOW_SIZE,
    build_vad,
    drain_segments,
    run_stream,
)


class EnglishMeetingASR(RoutedASR):
    """Forced-English variant that does not require the omnilingual fallback.

    The base RoutedASR normally tries the large omnilingual model when a
    specialist returns an empty string. In a fixed-English meeting this is
    undesirable: it adds a large download for a fallback that is rarely useful
    and may be triggered by non-speech. VAD already removes most non-speech, so
    keeping an empty Parakeet result is safer and keeps the one-click install
    small.
    """

    def transcribe(self, samples: np.ndarray, sample_rate: int,
                   known_lang: str | None = None, speech_s: float | None = None,
                   live: bool = True) -> dict:
        t0 = time.perf_counter()
        rec, tier = self._route("en")
        text = self._replace(self._decode(rec, samples, sample_rate))
        decode_ms = (time.perf_counter() - t0) * 1000
        if live and text.strip():
            self.last_lang = "en"
        return {
            "text": text,
            "lang": "en",
            "tier": tier,
            "lid_ms": 0.0,
            "decode_ms": decode_ms,
            "probe_ms": 0.0,
        }


def _require_pyaudiowpatch():
    if sys.platform != "win32":
        raise RuntimeError("System-audio meeting captions currently require Windows.")
    try:
        import pyaudiowpatch as pyaudio
    except ImportError as exc:
        raise RuntimeError(
            "PyAudioWPatch is not installed. Run meeting_captions.bat once, "
            "or install it with: pip install PyAudioWPatch==0.2.12.8"
        ) from exc
    return pyaudio


def _loopback_device(p, device_index: int | None):
    if device_index is None:
        return p.get_default_wasapi_loopback()

    info = p.get_device_info_by_index(device_index)
    if info.get("isLoopbackDevice"):
        return info

    try:
        return p.get_wasapi_loopback_analogue_by_dict(info)
    except (LookupError, OSError) as exc:
        raise RuntimeError(
            f"Audio device {device_index} has no WASAPI loopback counterpart. "
            "Run with --list-devices and choose a loopback device."
        ) from exc


def list_loopback_devices() -> None:
    pyaudio = _require_pyaudiowpatch()
    with pyaudio.PyAudio() as p:
        try:
            default = p.get_default_wasapi_loopback()
            default_index = int(default["index"])
        except (OSError, LookupError):
            default_index = -1

        print("WASAPI loopback devices (PC playback capture):")
        for dev in p.get_loopback_device_info_generator():
            idx = int(dev["index"])
            mark = " *default*" if idx == default_index else ""
            print(
                f"  {idx:>3}: {dev['name']}  "
                f"{int(dev['defaultSampleRate'])} Hz, "
                f"{int(dev['maxInputChannels'])} ch{mark}"
            )


def system_audio_chunks(device_index: int | None = None):
    """Yield 16-kHz mono float32 chunks from Windows WASAPI loopback.

    PyAudioWPatch callbacks may stop arriving when an output endpoint is truly
    idle. That would prevent hayamimi's VAD from seeing the silence needed to
    finalize the previous utterance. A short queue timeout therefore emits a
    synthetic silence chunk. This keeps caption finalization responsive even
    between speakers or when the meeting app momentarily stops its audio
    stream.
    """
    pyaudio = _require_pyaudiowpatch()
    audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=128)

    with pyaudio.PyAudio() as p:
        try:
            dev = _loopback_device(p, device_index)
        except (OSError, LookupError) as exc:
            raise RuntimeError(
                "No WASAPI loopback device was found. Make sure Windows has a "
                "default playback device, then run with --list-devices."
            ) from exc

        source_rate = int(dev["defaultSampleRate"])
        channels = max(1, int(dev["maxInputChannels"]))
        frames_per_buffer = max(
            128, int(round(source_rate * WINDOW_SIZE / SAMPLE_RATE))
        )

        print(
            f"system audio: [{int(dev['index'])}] {dev['name']} "
            f"({source_rate} Hz, {channels} ch) -> {SAMPLE_RATE} Hz mono",
            file=sys.stderr,
        )

        dropped = 0

        def callback(in_data, frame_count, time_info, status):
            nonlocal dropped
            if status:
                print(f"system-audio status: {status}", file=sys.stderr)
            try:
                audio_q.put_nowait(in_data)
            except queue.Full:
                # Never block the PortAudio callback. Prefer fresh meeting
                # audio over stale queued audio if the CPU briefly falls behind.
                try:
                    audio_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    audio_q.put_nowait(in_data)
                except queue.Full:
                    dropped += 1
                    if dropped == 1 or dropped % 100 == 0:
                        print(
                            f"system-audio warning: dropped {dropped} callback chunk(s)",
                            file=sys.stderr,
                        )
            return (None, pyaudio.paContinue)

        stream = p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=source_rate,
            input=True,
            input_device_index=int(dev["index"]),
            frames_per_buffer=frames_per_buffer,
            stream_callback=callback,
            start=False,
        )

        pending = np.zeros(0, dtype=np.float32)
        silence_timeout = max(0.040, WINDOW_SIZE / SAMPLE_RATE * 1.25)

        try:
            stream.start_stream()
            while stream.is_active():
                try:
                    raw = audio_q.get(timeout=silence_timeout)
                    mono = decode_pcm16(raw, channels=channels)
                    converted = resample_linear(mono, source_rate, SAMPLE_RATE)
                except queue.Empty:
                    # WASAPI can stop producing packets for genuine endpoint
                    # silence. Feed silence ourselves so VAD endpointing keeps
                    # advancing in wall-clock time.
                    converted = np.zeros(WINDOW_SIZE, dtype=np.float32)

                if len(converted):
                    pending = np.concatenate([pending, converted])
                while len(pending) >= WINDOW_SIZE:
                    yield pending[:WINDOW_SIZE]
                    pending = pending[WINDOW_SIZE:]
        finally:
            if stream.is_active():
                stream.stop_stream()
            stream.close()


def _open_dashboard_later(port: int) -> None:
    url = f"http://localhost:{port}/dashboard"

    def open_it():
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Timer(0.6, open_it).start()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", type=int, default=None,
                    help="WASAPI playback/loopback device index; default = Windows default output")
    ap.add_argument("--list-devices", action="store_true",
                    help="list available WASAPI loopback devices and exit")
    ap.add_argument("--port", type=int, default=8833,
                    help="local dashboard port (default 8833)")
    ap.add_argument("--threads", type=int, default=4,
                    help="Parakeet inference threads (default 4)")
    ap.add_argument("--min-silence", type=float, default=0.20,
                    help="silence that finalizes an utterance (default 0.20 s)")
    ap.add_argument("--max-speech", type=float, default=12.0,
                    help="force-finalize continuous speech after this many seconds")
    ap.add_argument("--no-refine", action="store_true",
                    help="disable hayamimi's second-pass transcript refinement")
    ap.add_argument("--no-browser", action="store_true",
                    help="do not automatically open the dashboard")
    ap.add_argument("--transcript", metavar="PATH", default=None,
                    help="optional path to append refined transcript text")
    args = ap.parse_args()

    if args.list_devices:
        list_loopback_devices()
        return 0

    # Fail clearly before loading ASR if system audio is unavailable.
    _require_pyaudiowpatch()

    from subtitle_server import SubtitleServer

    server = SubtitleServer(port=args.port).start()
    print(
        f"meeting captions: http://localhost:{args.port}/dashboard",
        file=sys.stderr,
    )
    if not args.no_browser:
        _open_dashboard_later(args.port)

    print("loading English caption model...", file=sys.stderr)
    asr = EnglishMeetingASR(
        threads=args.threads,
        warmup=False,
        preload=False,
        max_resident=1,
        punctuate=False,
        dual_confirm=False,
        forced_lang="en",
    )

    # Warm Parakeet itself, without loading the Japanese tier or the other
    # multilingual tiers. This removes the one-time model-load pause from the
    # first actual sentence in the meeting.
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    rec, _tier = asr._route("en")
    asr._decode(rec, silence, SAMPLE_RATE)

    vad = build_vad(args.min_silence, args.max_speech)
    stats = SessionStats()
    printer = PartialPrinter(enabled=True, server=server)
    history = AudioHistory(SAMPLE_RATE)
    refiner = None if args.no_refine else Refiner(
        asr,
        history,
        SAMPLE_RATE,
        printer,
        transcript_path=args.transcript,
        stats=stats,
    )

    def finish() -> None:
        vad.flush()
        drain_segments(
            vad,
            SAMPLE_RATE,
            asr,
            stats,
            printer,
            history,
            refiner=refiner,
        )
        if refiner is not None:
            refiner.maybe_refine(0, force=True)

    try:
        server.publish({"type": "session_start"})
        run_stream(
            system_audio_chunks(args.device),
            vad,
            SAMPLE_RATE,
            asr,
            stats,
            printer,
            refiner,
            history,
        )
    except KeyboardInterrupt:
        finish()
    except RuntimeError as exc:
        print(f"\nmeeting captions error: {exc}", file=sys.stderr)
        return 2
    finally:
        print(f"\n=== session summary: {stats.summary()} ===")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
