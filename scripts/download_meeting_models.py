r"""Download only the models needed by the Windows meeting-caption launcher.

This intentionally avoids hayamimi's full multilingual model set. Meeting mode
forces English and therefore only needs:
  * whisper-tiny (RoutedASR currently constructs the LID engine at startup)
  * Silero VAD
  * Parakeet TDT 0.6B v3 (English ASR)

Run from the repository root with:
    .venv\Scripts\python scripts\download_meeting_models.py
"""

import os

from download_models import (
    ASR_TAG,
    GITHUB_RELEASES,
    MODELS_DIR,
    download_and_extract_tarbz2,
    download_file,
)


def main() -> None:
    os.makedirs(MODELS_DIR, exist_ok=True)
    print("hayamimi meeting-caption model download (English only)")

    download_and_extract_tarbz2(
        f"{GITHUB_RELEASES}/{ASR_TAG}/sherpa-onnx-whisper-tiny.tar.bz2",
        "sherpa-onnx-whisper-tiny",
        "whisper-tiny (startup/LID dependency)",
    )

    download_file(
        f"{GITHUB_RELEASES}/{ASR_TAG}/silero_vad.onnx",
        os.path.join(MODELS_DIR, "silero_vad.onnx"),
        "Silero VAD",
    )

    download_and_extract_tarbz2(
        f"{GITHUB_RELEASES}/{ASR_TAG}/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2",
        "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
        "Parakeet TDT 0.6B v3 (English ASR)",
    )

    print("\nMeeting-caption models are ready.")


if __name__ == "__main__":
    main()
