@echo off
setlocal enabledelayedexpansion
title SIQspeak Setup
echo.
echo   ===========================
echo    SIQspeak Setup
echo   ===========================
echo.

:: ------------------------------------------------------------------
:: 1. Check Python
:: ------------------------------------------------------------------
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!] Python was not found on your system.
    echo.
    echo   Please install Python 3.10 or later from:
    echo   https://www.python.org/downloads/
    echo.
    echo   IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Verify version is 3.10+
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   [OK] Python %PYVER% found.

:: ------------------------------------------------------------------
:: 2. Create virtual environment
:: ------------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo   [..] Creating virtual environment...
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo   [!] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo   [OK] Virtual environment created.
) else (
    echo   [OK] Virtual environment already exists.
)

:: ------------------------------------------------------------------
:: 3. Install / upgrade dependencies
:: ------------------------------------------------------------------
echo   [..] Installing dependencies...
.venv\Scripts\pip install --upgrade pip >nul 2>&1
.venv\Scripts\pip install -e .
if %errorlevel% neq 0 (
    echo   [!] Failed to install dependencies.
    pause
    exit /b 1
)
echo   [OK] Dependencies installed.
echo.

:: ------------------------------------------------------------------
:: 4. GPU auto-detection and CUDA runtime
:: ------------------------------------------------------------------
set HAS_GPU=0
nvidia-smi >nul 2>&1
if !errorlevel! equ 0 (
    echo   [OK] NVIDIA GPU detected. Installing CUDA runtime libraries...
    echo        (nvidia-cublas-cu12 + nvidia-cudnn-cu12, ~600 MB^)
    .venv\Scripts\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
    if !errorlevel! equ 0 (
        set HAS_GPU=1
        echo   [OK] GPU acceleration enabled.
    ) else (
        echo   [!] GPU libraries failed to install. App will use CPU.
    )
) else (
    echo   [--] No NVIDIA GPU detected. Using CPU mode.
)
echo.

:: ------------------------------------------------------------------
:: 5. Pre-download default model
:: ------------------------------------------------------------------
echo   The default speech model (tiny, ~75 MB) will be downloaded
echo   on first use if not already available.
echo.
set /p PREDOWNLOAD="   Download it now? (Y/N): "
if /i "%PREDOWNLOAD%"=="Y" (
    echo.
    echo   [..] Downloading tiny model (~75 MB^)...
    echo       This may take a minute depending on your connection.
    echo.
    if !HAS_GPU! equ 1 (
        .venv\Scripts\python.exe -c "import sys; sys.stderr = sys.stdout; from faster_whisper import WhisperModel; print('   [..] Loading model...'); m = WhisperModel('tiny', device='cuda', compute_type='float16'); print('   [OK] Model ready.')" 2>&1
    ) else (
        .venv\Scripts\python.exe -c "import sys; sys.stderr = sys.stdout; from faster_whisper import WhisperModel; print('   [..] Loading model...'); m = WhisperModel('tiny', device='cpu', compute_type='int8'); print('   [OK] Model ready.')" 2>&1
    )
    if !errorlevel! neq 0 (
        echo.
        echo   [!] Model download failed. This is usually a network issue.
        echo       The model will download automatically on first use.
        echo       You can also re-run setup.bat to try again.
        echo.
        pause
    )
) else (
    echo   [--] Skipped. Model will download on first use.
)
echo.

:: ------------------------------------------------------------------
:: 6. Offer desktop shortcut
:: ------------------------------------------------------------------
set /p SHORTCUT="   Create a desktop shortcut? (Y/N): "
if /i "%SHORTCUT%"=="Y" (
    echo   [..] Creating desktop shortcut...
    powershell -NoProfile -Command ^
        "$ws = New-Object -ComObject WScript.Shell; ^
         $sc = $ws.CreateShortcut([IO.Path]::Combine($ws.SpecialFolders('Desktop'), 'SIQspeak.lnk')); ^
         $sc.TargetPath = (Resolve-Path '.venv\Scripts\pythonw.exe').Path; ^
         $sc.Arguments = '-m siqspeak'; ^
         $sc.WorkingDirectory = (Resolve-Path '.').Path; ^
         $sc.IconLocation = (Resolve-Path 'dictate.ico').Path + ',0'; ^
         $sc.Description = 'SIQspeak - local speech-to-text'; ^
         $sc.Save()"
    if !errorlevel! equ 0 (
        echo   [OK] Desktop shortcut created.
    ) else (
        echo   [!] Could not create shortcut. You can do it manually later.
    )
) else (
    echo   [--] Skipped desktop shortcut.
)
echo.

:: ------------------------------------------------------------------
:: 7. Offer to run now
:: ------------------------------------------------------------------
set /p RUNNOW="   Run SIQspeak now? (Y/N): "
if /i "%RUNNOW%"=="Y" (
    echo   [..] Starting SIQspeak...
    start "" ".venv\Scripts\pythonw.exe" -m siqspeak
    echo   [OK] SIQspeak is running in the system tray.
) else (
    echo.
    echo   To run later, double-click the desktop shortcut or run:
    echo     .venv\Scripts\pythonw.exe -m siqspeak
)

echo.
echo   ===========================
echo    Setup complete!
echo   ===========================
echo.
pause
