@echo off
setlocal
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
    if %errorlevel% neq 0 (
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
.venv\Scripts\pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo   [!] Failed to install dependencies.
    pause
    exit /b 1
)
echo   [OK] Dependencies installed.
echo.

:: ------------------------------------------------------------------
:: 4. Pre-download default model
:: ------------------------------------------------------------------
echo   The default speech model (tiny, ~75 MB) will be downloaded
echo   on first use if not already available.
echo.
set /p PREDOWNLOAD="   Download it now? (Y/N): "
if /i "%PREDOWNLOAD%"=="Y" (
    echo   [..] Downloading tiny model (~75 MB)...
    .venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8')"
    if %errorlevel% equ 0 (
        echo   [OK] Model downloaded and ready.
    ) else (
        echo   [!] Download failed. The model will download on first use.
    )
) else (
    echo   [--] Skipped. Model will download on first use.
)
echo.

:: ------------------------------------------------------------------
:: 5. Offer desktop shortcut
:: ------------------------------------------------------------------
set /p SHORTCUT="   Create a desktop shortcut? (Y/N): "
if /i "%SHORTCUT%"=="Y" (
    echo   [..] Creating desktop shortcut...
    powershell -NoProfile -Command ^
        "$ws = New-Object -ComObject WScript.Shell; ^
         $sc = $ws.CreateShortcut([IO.Path]::Combine($ws.SpecialFolders('Desktop'), 'SIQspeak.lnk')); ^
         $sc.TargetPath = (Resolve-Path '.venv\Scripts\pythonw.exe').Path; ^
         $sc.Arguments = (Resolve-Path 'dictate.py').Path; ^
         $sc.WorkingDirectory = (Resolve-Path '.').Path; ^
         $sc.IconLocation = (Resolve-Path 'dictate.ico').Path + ',0'; ^
         $sc.Description = 'SIQspeak — local speech-to-text'; ^
         $sc.Save()"
    if %errorlevel% equ 0 (
        echo   [OK] Desktop shortcut created.
    ) else (
        echo   [!] Could not create shortcut. You can do it manually later.
    )
) else (
    echo   [--] Skipped desktop shortcut.
)
echo.

:: ------------------------------------------------------------------
:: 6. Offer to run now
:: ------------------------------------------------------------------
set /p RUNNOW="   Run SIQspeak now? (Y/N): "
if /i "%RUNNOW%"=="Y" (
    echo   [..] Starting SIQspeak...
    start "" ".venv\Scripts\pythonw.exe" dictate.py
    echo   [OK] SIQspeak is running in the system tray.
) else (
    echo.
    echo   To run later, double-click the desktop shortcut or run:
    echo     .venv\Scripts\pythonw.exe dictate.py
)

echo.
echo   ===========================
echo    Setup complete!
echo   ===========================
echo.
pause
