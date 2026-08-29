@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ============================================
echo   hayamimi - English Meeting Captions
echo ============================================
echo.

if not exist "scripts\meeting_captions.py" (
  echo [ERROR] scripts\meeting_captions.py was not found.
  echo Run this file from the hayamimi repository root.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [first run] Creating Python virtual environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo [ERROR] Python 3.10 or newer was not found.
      echo Install Python, then double-click this file again.
      pause
      exit /b 1
    )
    python -m venv .venv
  )
  if errorlevel 1 goto :failed
)

set "PY=.venv\Scripts\python.exe"

"%PY%" -c "import numpy, sherpa_onnx, onnxruntime, pyaudiowpatch" >nul 2>nul
if errorlevel 1 (
  echo [first run] Installing meeting-caption dependencies...
  "%PY%" -m pip install --upgrade pip
  if errorlevel 1 goto :failed
  "%PY%" -m pip install -r requirements-meeting.txt
  if errorlevel 1 goto :failed
)

if not exist "models\silero_vad.onnx" goto :models
if not exist "models\sherpa-onnx-whisper-tiny\tiny-encoder.int8.onnx" goto :models
if not exist "models\sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8\tokens.txt" goto :models
goto :launch

:models
echo [first run] Downloading the English ASR models...
"%PY%" scripts\download_meeting_models.py
if errorlevel 1 goto :failed

:launch
echo.
echo Capturing the Windows default playback device.
echo Keep Teams / Zoom / Meet audio playing through your normal headphones.
echo The dashboard will open automatically. Press Ctrl+C here to stop.
echo.
"%PY%" scripts\meeting_captions.py
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo If your meeting app uses a different output device, run:
  echo   "%PY%" scripts\meeting_captions.py --list-devices
  echo then launch with:
  echo   "%PY%" scripts\meeting_captions.py --device DEVICE_NUMBER
  echo.
  pause
)
exit /b %EXITCODE%

:failed
echo.
echo [ERROR] Setup failed. Review the messages above.
pause
exit /b 1
