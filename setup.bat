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
:: 5. HuggingFace authentication
:: ------------------------------------------------------------------
echo   ------------------------------------------
echo    HuggingFace Sign-In (one-time setup)
echo   ------------------------------------------
echo.
echo   SIQspeak downloads AI models from HuggingFace.
echo   A free account is required.
echo.

:: Check if already authenticated
.venv\Scripts\python.exe -c "from huggingface_hub import HfFolder; t=HfFolder.get_token(); exit(0 if t else 1)" 2>nul
if !errorlevel! equ 0 (
    :: Validate existing token
    .venv\Scripts\python.exe -c "from huggingface_hub import whoami; u=whoami(); print(f'   [OK] Already signed in as: {u[\"name\"]}')" 2>nul
    if !errorlevel! equ 0 (
        goto :hf_done
    ) else (
        echo   [!] Existing token is invalid. Let's sign in again.
    )
)

:hf_auth_start
echo.
set /p HAS_ACCOUNT="   Do you have a HuggingFace account? (Y/N): "
if /i "!HAS_ACCOUNT!"=="N" (
    echo.
    echo   [..] Opening HuggingFace signup in your browser...
    echo       Create a free account, then come back here.
    start "" "https://huggingface.co/join"
    echo.
    echo   Press any key after creating your account...
    pause >nul
    echo.
)

echo   [..] Opening token creation page in your browser...
echo.
echo       1. Sign in if prompted
echo       2. Click "Create token" (keep "Read" permission)
echo       3. Copy the token (starts with hf_)
echo.
start "" "https://huggingface.co/settings/tokens/new?tokenName=SIQspeak&globalPermissions=read"

echo   Waiting for you to copy the token...
echo.
set /p HF_TOKEN="   Paste your token here: "

if "!HF_TOKEN!"=="" (
    echo   [!] No token entered.
    goto :hf_skip
)

:: Validate and save token
.venv\Scripts\python.exe -c "import sys; exec(\"\"\"
from huggingface_hub import whoami, login
token = sys.argv[1].strip()
if not token.startswith('hf_'):
    print('   [!] Token should start with hf_ -- check and try again.')
    sys.exit(1)
try:
    info = whoami(token=token)
    username = info.get('name', 'unknown')
    login(token=token, add_to_git_credential=False)
    print(f'   [OK] Signed in as: {username}')
    print(f'   [OK] Token saved. You won\\'t need to do this again.')
except Exception as e:
    print(f'   [!] Token validation failed: {e}')
    print(f'   [!] Check that you copied the full token.')
    sys.exit(1)
\"\"\")" "!HF_TOKEN!"

if !errorlevel! neq 0 (
    echo.
    set /p RETRY="   Try again? (Y/N): "
    if /i "!RETRY!"=="Y" goto :hf_auth_start
    goto :hf_skip
)
goto :hf_done

:hf_skip
echo.
echo   [--] Skipping HuggingFace sign-in.
echo       Model downloads may fail without authentication.
echo       You can run setup.bat again to sign in later.
echo.

:hf_done
echo.

:: ------------------------------------------------------------------
:: 6. Pre-download default model
:: ------------------------------------------------------------------
echo   [..] Downloading default speech model (tiny, ~75 MB^)...
echo       This may take a minute depending on your connection.
echo.

if !HAS_GPU! equ 1 (
    .venv\Scripts\python.exe -c "import sys; sys.stderr = sys.stdout; from faster_whisper import WhisperModel; print('   [..] Loading model...'); m = WhisperModel('tiny', device='cuda', compute_type='float16'); print('   [OK] Model ready.')" 2>&1
) else (
    .venv\Scripts\python.exe -c "import sys; sys.stderr = sys.stdout; from faster_whisper import WhisperModel; print('   [..] Loading model...'); m = WhisperModel('tiny', device='cpu', compute_type='int8'); print('   [OK] Model ready.')" 2>&1
)

if !errorlevel! neq 0 (
    echo.
    echo   [!] Model download failed.
    echo.
    echo   Trying alternative download method...
    echo.
    .venv\Scripts\python.exe -c "import sys; exec(\"\"\"
import os, urllib.request
cache_base = os.path.join(os.path.expanduser('~'), '.cache', 'huggingface', 'hub')
model_dir = os.path.join(cache_base, 'models--Systran--faster-whisper-tiny', 'snapshots', 'main')
os.makedirs(model_dir, exist_ok=True)
base_url = 'https://huggingface.co/Systran/faster-whisper-tiny/resolve/main'
files = ['model.bin', 'config.json', 'tokenizer.json', 'preprocessor_config.json', 'vocabulary.json', 'vocabulary.txt']
for fname in files:
    dest = os.path.join(model_dir, fname)
    if os.path.exists(dest):
        print(f'   [OK] {fname} exists')
        continue
    url = f'{base_url}/{fname}'
    print(f'   [..] Downloading {fname}...')
    try:
        urllib.request.urlretrieve(url, dest)
        print(f'   [OK] {fname}')
    except Exception as e:
        print(f'   [!] {fname} failed: {e}')
        if fname == 'model.bin':
            print('   [!] Critical file failed. Model will not work offline.')
            sys.exit(1)
# Verify
from faster_whisper import WhisperModel
m = WhisperModel(model_dir, device='cpu', compute_type='int8')
del m
print('   [OK] Model verified.')
\"\"\")" 2>&1
    if !errorlevel! neq 0 (
        echo.
        echo   [!] Both download methods failed.
        echo       SIQspeak will try again on first launch.
        echo       Check your firewall/antivirus settings.
        echo.
    )
)
echo.

:: ------------------------------------------------------------------
:: 7. Offer desktop shortcut
:: ------------------------------------------------------------------
set /p SHORTCUT="   Create a desktop shortcut? (Y/N): "
if /i "%SHORTCUT%"=="Y" (
    echo   [..] Creating desktop shortcut...
    set "VENVPY=%SIQDIR%.venv\Scripts\pythonw.exe"
    set "ICOFILE=%SIQDIR%dictate.ico"

    if not exist "!VENVPY!" (
        echo   [!] Could not find pythonw.exe at: !VENVPY!
        echo       Shortcut creation skipped.
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
:: 8. Offer to run now
:: ------------------------------------------------------------------
set /p RUNNOW="   Run SIQspeak now? (Y/N): "
if /i "%RUNNOW%"=="Y" (
    echo   [..] Starting SIQspeak...
    start "" "%SIQDIR%.venv\Scripts\pythonw.exe" -m siqspeak
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
