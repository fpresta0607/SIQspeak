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
:: 5. Pre-download default model
:: ------------------------------------------------------------------
echo   The default speech model (tiny, ~75 MB) will be downloaded now.
echo.

:: Try downloading via the app's built-in download (handles HF auth gracefully)
echo   [..] Downloading tiny model (~75 MB^)...
echo       This may take a minute depending on your connection.
echo.

.venv\Scripts\python.exe -c "import sys; sys.stderr = sys.stdout; exec(\"\"\"
import os, sys

# Method 1: Try HuggingFace hub download (works if no auth required or token is set)
try:
    from faster_whisper import WhisperModel
    m = WhisperModel('tiny', device='cpu', compute_type='int8')
    del m
    print('   [OK] Model downloaded and verified.')
    sys.exit(0)
except Exception as e:
    print(f'   [..] HuggingFace direct download failed: {e}')
    print('   [..] Trying alternative download method...')

# Method 2: Download model files directly from HuggingFace without hub auth
try:
    import urllib.request
    import hashlib
    
    # Create cache directory that faster-whisper expects
    cache_base = os.path.join(os.path.expanduser('~'), '.cache', 'huggingface', 'hub')
    model_dir = os.path.join(cache_base, 'models--Systran--faster-whisper-tiny', 'snapshots', 'main')
    os.makedirs(model_dir, exist_ok=True)
    
    base_url = 'https://huggingface.co/Systran/faster-whisper-tiny/resolve/main'
    files = ['model.bin', 'config.json', 'tokenizer.json', 'preprocessor_config.json', 'vocabulary.json', 'vocabulary.txt']
    
    for fname in files:
        dest = os.path.join(model_dir, fname)
        if os.path.exists(dest):
            print(f'   [OK] {fname} already exists')
            continue
        url = f'{base_url}/{fname}'
        print(f'   [..] Downloading {fname}...')
        try:
            urllib.request.urlretrieve(url, dest)
            print(f'   [OK] {fname} downloaded')
        except Exception as fe:
            print(f'   [--] {fname} skipped: {fe}')
    
    # Verify the model loads
    from faster_whisper import WhisperModel
    m = WhisperModel(model_dir, device='cpu', compute_type='int8')
    del m
    print('   [OK] Model verified successfully.')
    sys.exit(0)
except Exception as e2:
    print(f'   [!] Alternative download also failed: {e2}')
    print()
    print('   The model will try to download again when you first run SIQspeak.')
    print('   If downloads keep failing, check your firewall/antivirus settings.')
    print('   You can also manually place model files in the HF cache directory.')
    sys.exit(1)
\"\"\")" 2>&1

if !errorlevel! neq 0 (
    echo.
    echo   [!] Model download had issues but setup can continue.
    echo       SIQspeak will retry the download on first launch.
    echo.
)
echo.

:: ------------------------------------------------------------------
:: 6. Offer desktop shortcut
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
:: 7. Offer to run now
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
