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
:: 4. GPU detection
:: ------------------------------------------------------------------
set HAS_GPU=0
nvidia-smi >nul 2>&1
if !errorlevel! neq 0 goto :no_gpu
echo   [OK] NVIDIA GPU detected. Installing CUDA libraries...
.venv\Scripts\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
if !errorlevel! equ 0 set HAS_GPU=1
if !HAS_GPU! equ 1 echo   [OK] GPU acceleration enabled.
if !HAS_GPU! equ 0 echo   [!] GPU install failed. Using CPU.
goto :gpu_done

:no_gpu
echo   [--] No NVIDIA GPU detected. Using CPU mode.

:gpu_done
echo.

:: ------------------------------------------------------------------
:: 5. HuggingFace Sign-In
:: ------------------------------------------------------------------
echo   ------------------------------------------
echo    HuggingFace Sign-In
echo   ------------------------------------------
echo.
echo   SIQspeak downloads AI speech models from HuggingFace.
echo   A free account is needed to download models.
echo.

:: Check existing token
.venv\Scripts\python.exe scripts\hf_check.py 2>nul
if !errorlevel! equ 0 goto :hf_done

:hf_auth_start
echo.
set /p HAS_ACCOUNT="   Do you have a HuggingFace account? [Y/N]: "
if /i "!HAS_ACCOUNT!"=="N" goto :hf_signup
goto :hf_get_token

:hf_signup
echo.
echo   No problem -- we will create one now. It is free.
echo.
echo   [..] Opening HuggingFace signup in your browser...
echo.
echo       - Pick a username and password
echo       - Verify your email if prompted
echo       - Then come back to this window
echo.
start "" "https://huggingface.co/join"
echo   Press any key after you have created your account...
pause >nul
echo.

:hf_get_token
echo.
echo   Now we need an Access Token so SIQspeak can download models.
echo.
echo   Your browser will open to the HuggingFace token page.
echo   Here is exactly what to do:
echo.
echo       STEP 1: Log in if prompted
echo.
echo       STEP 2: You will see a "Create a new token" form
echo               - "Token name" will say SIQspeak -- leave it
echo               - Under "Token type" select "Read"
echo                 That is all SIQspeak needs
echo.
echo       STEP 3: Click the blue "Create token" button at the bottom
echo.
echo       STEP 4: Your new token appears -- it starts with hf_
echo               Click the COPY ICON next to it to copy
echo.
echo       STEP 5: Come back to this window and paste it below
echo               Tip: right-click in this window to paste
echo.
echo   Opening browser now...
echo.
start "" "https://huggingface.co/settings/tokens/new?tokenName=SIQspeak&globalPermissions=read"

echo.
set /p HF_TOKEN="   Paste your token here: "

if "!HF_TOKEN!"=="" goto :hf_empty_token

:: Validate using external script
.venv\Scripts\python.exe scripts\hf_login.py "!HF_TOKEN!"
if !errorlevel! equ 0 goto :hf_done
goto :hf_retry

:hf_empty_token
echo   [!] No token entered.

:hf_retry
echo.
set /p RETRY="   Try again? [Y/N]: "
if /i "!RETRY!"=="Y" goto :hf_auth_start

echo.
echo   [--] Skipping sign-in. Model downloads may fail.
echo       Run setup.bat again later to sign in.
echo.

:hf_done
echo.

:: ------------------------------------------------------------------
:: 6. Download default model
:: ------------------------------------------------------------------
echo   [..] Downloading default speech model -- tiny, about 75 MB
echo       This may take a minute.
echo.

.venv\Scripts\python.exe scripts\download_model.py tiny
if !errorlevel! equ 0 goto :model_done

echo.
echo   [..] Primary download failed. Trying alternative...
.venv\Scripts\python.exe -c "import os,urllib.request,sys;d=os.path.join(os.path.expanduser('~'),'.cache','huggingface','hub','models--Systran--faster-whisper-tiny','snapshots','main');os.makedirs(d,exist_ok=True);[urllib.request.urlretrieve('https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/'+f,os.path.join(d,f)) or print('   [OK] '+f) for f in ['model.bin','config.json','tokenizer.json','preprocessor_config.json','vocabulary.json','vocabulary.txt'] if not os.path.exists(os.path.join(d,f))]"
if !errorlevel! equ 0 goto :model_done

echo   [!] Model download failed. SIQspeak will retry on first launch.

:model_done
echo.

:: ------------------------------------------------------------------
:: 7. Desktop shortcut
:: ------------------------------------------------------------------
set /p SHORTCUT="   Create a desktop shortcut? [Y/N]: "
if /i "!SHORTCUT!"=="Y" goto :make_shortcut
echo   [--] Skipped desktop shortcut.
goto :shortcut_done

:make_shortcut
echo   [..] Creating desktop shortcut...

if not exist "!SIQDIR!.venv\Scripts\pythonw.exe" goto :shortcut_missing
powershell -NoProfile -ExecutionPolicy Bypass -File "!SIQDIR!scripts\create_shortcut.ps1" -SiqDir "!SIQDIR!"
goto :shortcut_done

:shortcut_missing
echo   [!] pythonw.exe not found. Shortcut skipped.

:shortcut_done
echo.

:: ------------------------------------------------------------------
:: 8. Run now?
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
