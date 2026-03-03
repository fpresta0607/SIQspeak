@echo off
setlocal enabledelayedexpansion
title SIQspeak Setup
echo.
echo   ===========================
echo    SIQspeak Setup
echo   ===========================
echo.

:: Save our directory so shortcuts and paths resolve correctly
set "SIQDIR=%~dp0"
cd /d "%SIQDIR%"

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
    echo.
    echo   Common fixes:
    echo     - Make sure you have internet access
    echo     - Try: .venv\Scripts\pip install -e . --no-cache-dir
    echo     - Install Visual C++ Redistributable if you see "DLL load failed"
    echo       https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo.
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
:: 5. HuggingFace Sign-In (one-time setup)
:: ------------------------------------------------------------------
echo   ------------------------------------------
echo    HuggingFace Sign-In  (one-time setup)
echo   ------------------------------------------
echo.
echo   SIQspeak downloads AI speech models from HuggingFace.
echo   A free account is needed to download models.
echo.

:: Check if already authenticated
.venv\Scripts\python.exe scripts\hf_check.py 2>nul
if !errorlevel! equ 0 (
    echo   Token is still valid. Skipping sign-in.
    goto :hf_done
)

:hf_auth_start
echo.
set /p HAS_ACCOUNT="   Do you have a HuggingFace account? (Y/N): "
if /i "!HAS_ACCOUNT!"=="N" (
    echo.
    echo   No problem! Let's create one (it's free).
    echo.
    echo   [..] Opening HuggingFace signup in your browser...
    echo.
    echo       - Pick a username and password
    echo       - Verify your email if prompted
    echo       - Then come back here
    echo.
    start "" "https://huggingface.co/join"
    echo   Press any key after you have created your account...
    pause >nul
    echo.
)

echo.
echo   Now we need an Access Token so SIQspeak can download models.
echo.
echo   Your browser will open to the HuggingFace token page.
echo   Follow these steps:
echo.
echo       1. Log in if prompted (use the account you just created)
echo.
echo       2. You will see a "Create a new token" form:
echo          - Token name: SIQspeak  (already filled in)
echo          - Token type: select "Read" (this is all SIQspeak needs)
echo.
echo       3. Click the "Create token" button
echo.
echo       4. Your token will appear (starts with hf_)
echo          Click the COPY icon next to it
echo.
echo       5. Come back here and paste it
echo.
echo   Opening browser now...
echo.
start "" "https://huggingface.co/settings/tokens/new?tokenName=SIQspeak&globalPermissions=read"

echo.
set /p HF_TOKEN="   Paste your token here (right-click to paste): "

if "!HF_TOKEN!"=="" (
    echo.
    echo   [!] No token entered.
    goto :hf_retry_or_skip
)

:: Validate and save using external script (avoids batch escaping issues)
.venv\Scripts\python.exe scripts\hf_login.py "!HF_TOKEN!"
if !errorlevel! neq 0 (
    goto :hf_retry_or_skip
)
goto :hf_done

:hf_retry_or_skip
echo.
set /p RETRY="   Try again? (Y/N): "
if /i "!RETRY!"=="Y" goto :hf_auth_start

echo.
echo   [--] Skipping HuggingFace sign-in.
echo       Model downloads may fail without authentication.
echo       You can run setup.bat again later to sign in.
echo.

:hf_done
echo.

:: ------------------------------------------------------------------
:: 6. Download default model
:: ------------------------------------------------------------------
echo   [..] Downloading default speech model (tiny, ~75 MB)...
echo       This may take a minute.
echo.

.venv\Scripts\python.exe scripts\download_model.py tiny
if !errorlevel! neq 0 (
    echo.
    echo   [..] Primary download failed. Trying alternative method...
    .venv\Scripts\python.exe -c "import os,urllib.request,sys;d=os.path.join(os.path.expanduser('~'),'.cache','huggingface','hub','models--Systran--faster-whisper-tiny','snapshots','main');os.makedirs(d,exist_ok=True);[urllib.request.urlretrieve(f'https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/{f}',os.path.join(d,f)) or print(f'   [OK] {f}') for f in ['model.bin','config.json','tokenizer.json','preprocessor_config.json','vocabulary.json','vocabulary.txt'] if not os.path.exists(os.path.join(d,f))]"
    if !errorlevel! neq 0 (
        echo.
        echo   [!] Model download failed. SIQspeak will retry on first launch.
    ) else (
        echo   [OK] Model downloaded via alternative method.
    )
)
echo.

:: ------------------------------------------------------------------
:: 7. Desktop shortcut
:: ------------------------------------------------------------------
set /p SHORTCUT="   Create a desktop shortcut? (Y/N): "
if /i "!SHORTCUT!"=="Y" (
    echo   [..] Creating desktop shortcut...

    if not exist "!SIQDIR!.venv\Scripts\pythonw.exe" (
        echo   [!] Could not find pythonw.exe. Shortcut skipped.
        goto :shortcut_done
    )

    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "try { ^
            $ws = New-Object -ComObject WScript.Shell; ^
            $desktop = $ws.SpecialFolders('Desktop'); ^
            $sc = $ws.CreateShortcut([IO.Path]::Combine($desktop, 'SIQspeak.lnk')); ^
            $sc.TargetPath = '%SIQDIR%.venv\Scripts\pythonw.exe'; ^
            $sc.Arguments = '-m siqspeak'; ^
            $sc.WorkingDirectory = '%SIQDIR%'; ^
            if (Test-Path '%SIQDIR%dictate.ico') { $sc.IconLocation = '%SIQDIR%dictate.ico,0' }; ^
            $sc.Description = 'SIQspeak - local speech-to-text'; ^
            $sc.Save(); ^
            Write-Host '   [OK] Desktop shortcut created.' ^
        } catch { ^
            Write-Host ('   [!] Shortcut failed: ' + $_.Exception.Message) ^
        }"
) else (
    echo   [--] Skipped desktop shortcut.
)
:shortcut_done
echo.

:: ------------------------------------------------------------------
:: 8. Run now?
:: ------------------------------------------------------------------
set /p RUNNOW="   Run SIQspeak now? (Y/N): "
if /i "!RUNNOW!"=="Y" (
    echo   [..] Starting SIQspeak...
    start "" "!SIQDIR!.venv\Scripts\pythonw.exe" -m siqspeak
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
