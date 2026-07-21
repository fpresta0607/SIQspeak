@echo off
setlocal enabledelayedexpansion
title SIQspeak Setup
echo.
echo   ===========================
echo    SIQspeak Setup
echo   ===========================
echo.

set "SIQDIR=%~dp0"
cd /d "%SIQDIR%"

:: ------------------------------------------------------------------
:: 1. Check Python
:: ------------------------------------------------------------------
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!] Python was not found on your system.
    echo       Install Python 3.10+ from https://www.python.org/downloads/
    echo       IMPORTANT: Check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   [OK] Python %PYVER% found.

:: ------------------------------------------------------------------
:: 2. Create virtual environment
:: ------------------------------------------------------------------
if exist ".venv\Scripts\python.exe" goto :venv_exists
echo   [..] Creating virtual environment...
python -m venv .venv
if !errorlevel! neq 0 (
    echo   [!] Failed to create virtual environment.
    pause
    exit /b 1
)
echo   [OK] Virtual environment created.
goto :venv_done

:venv_exists
echo   [OK] Virtual environment already exists.

:venv_done

:: ------------------------------------------------------------------
:: 3. Install dependencies
:: ------------------------------------------------------------------
echo   [..] Installing dependencies...
.venv\Scripts\pip install --upgrade pip >nul 2>&1
.venv\Scripts\pip install -e .
if !errorlevel! neq 0 (
    echo   [!] Failed to install dependencies.
    echo       Try: .venv\Scripts\pip install -e . --no-cache-dir
    pause
    exit /b 1
)
echo   [OK] Dependencies installed.
echo.

:: ------------------------------------------------------------------
:: 4. Download default speech model
:: ------------------------------------------------------------------
echo   [..] Downloading default speech model -- base.en, about 141 MB
echo       This may take a minute.
echo.

.venv\Scripts\python.exe scripts\download_model.py base.en
if !errorlevel! equ 0 goto :model_done

echo   [!] Model download failed. SIQspeak will retry on first launch.

:model_done
echo.

:: ------------------------------------------------------------------
:: 5. Optional local prompt enhancer (Ollama)
:: ------------------------------------------------------------------
echo   ------------------------------------------
echo    Optional local prompt enhancer
echo   ------------------------------------------
echo.
echo   SIQspeak can rewrite spoken requests into structured coding prompts
echo   using a local model. This runs entirely on your machine and is optional.
echo.
set /p ENHANCER="   Download the optional local prompt enhancer (~3.4 GB)? [Y/N]: "
if /i "!ENHANCER!"=="Y" goto :enhancer_yes
echo   [--] Skipped local prompt enhancer.
goto :enhancer_done

:enhancer_yes
where ollama >nul 2>&1
if !errorlevel! neq 0 goto :enhancer_no_ollama
echo   [..] Downloading local prompt enhancer -- qwen3.5:4b, about 3.4 GB
echo       This may take several minutes.
echo.
ollama pull qwen3.5:4b
if !errorlevel! equ 0 goto :enhancer_done
echo   [!] Enhancer download failed. Rerun setup.bat to try again.
goto :enhancer_done

:enhancer_no_ollama
echo   [!] Ollama is not installed.
echo       The local prompt enhancer needs Ollama for Windows.
echo       Opening the official download page...
start "" "https://ollama.com/download"
echo       After installing Ollama, rerun setup.bat to download the enhancer.

:enhancer_done
echo.

:: ------------------------------------------------------------------
:: 6. Desktop shortcut
:: ------------------------------------------------------------------
set /p SHORTCUT="   Create a desktop shortcut? [Y/N]: "
if /i "!SHORTCUT!"=="Y" goto :make_shortcut
echo   [--] Skipped desktop shortcut.
goto :shortcut_done

:make_shortcut
echo   [..] Creating desktop shortcut...

if not exist "!SIQDIR!.venv\Scripts\pythonw.exe" goto :shortcut_missing
powershell -NoProfile -ExecutionPolicy Bypass -File "!SIQDIR!scripts\create_shortcut.ps1"
goto :shortcut_done

:shortcut_missing
echo   [!] pythonw.exe not found. Shortcut skipped.

:shortcut_done
echo.

:: ------------------------------------------------------------------
:: 7. Run now?
:: ------------------------------------------------------------------
set /p RUNNOW="   Run SIQspeak now? [Y/N]: "
if /i "!RUNNOW!"=="Y" goto :run_now
echo.
echo   To run later: double-click the desktop shortcut or run:
echo     .venv\Scripts\pythonw.exe -m siqspeak
goto :finish

:run_now
echo   [..] Starting SIQspeak...
start "" "!SIQDIR!.venv\Scripts\pythonw.exe" -m siqspeak
echo   [OK] SIQspeak is running in the system tray.

:finish
echo.
echo   ===========================
echo    Setup complete!
echo   ===========================
echo.
pause
