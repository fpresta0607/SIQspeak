# SIQspeak

Local speech-to-text for Windows. Hold a hotkey, speak, release - your words are typed into the active window. No cloud, no API keys, 100% private.

Powered by OpenAI's [Whisper](https://github.com/openai/whisper) model running locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Download

**[Download SIQspeak-Setup.exe](https://github.com/fpresta0607/SIQspeak/releases/latest)** - No Python required. Just install and go.

The installer bundles everything you need, including the Whisper speech model. Works offline immediately after installation.

## Features

- **Hold-to-talk** - Hold `Ctrl+Shift+Space` to record, release to transcribe
- **Auto-type** - Transcribed text is typed directly into whatever window was active
- **100% local** - Whisper runs on your CPU, nothing leaves your machine
- **System tray** - Runs quietly in the background, right-click to quit
- **Visual overlay** - Animated floating pill shows recording/transcribing status with audio-reactive dots
- **Transcription history** - Hover the idle pill to see recent transcriptions, click to copy
- **No API keys** - No accounts, no subscriptions, no internet required after setup

## Requirements

Before you start, make sure you have:

- **Windows 10 or 11**
- **Python 3.10 or newer** - If you don't have Python yet, see Step 1 below
- **A microphone** - Any built-in or USB mic works

## Installation (Step by Step)

### Step 1: Install Python

If you already have Python 3.10+, skip to Step 2.

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Click the big yellow **"Download Python 3.x.x"** button
3. Run the installer
4. **IMPORTANT: Check the box at the bottom that says "Add Python to PATH"** before clicking Install
5. Click **Install Now** and wait for it to finish

To verify Python is installed, open a Command Prompt and type:
```
python --version
```
You should see something like `Python 3.12.x`. If you get an error, restart your computer and try again.

### Step 2: Download SIQspeak

1. Go to the [SIQspeak GitHub page](https://github.com/fpresta0607/SIQspeak)
2. Click the green **"Code"** button near the top right
3. Click **"Download ZIP"**
4. Once downloaded, **right-click the ZIP file** and select **"Extract All..."**
5. Extract it somewhere easy to find, like your **Desktop** or **Documents** folder
   - Example: `C:\Users\YourName\Desktop\SIQspeak-main`

### Step 3: Run the Setup

1. Open the extracted folder (e.g. `SIQspeak-main`)
2. Double-click **`setup.bat`**
3. A black command window will open and walk you through the setup:
   - It creates a Python virtual environment
   - Installs all dependencies
   - Detects if you have an NVIDIA GPU (optional, for faster transcription)
   - Asks if you want to pre-download the speech model (~75 MB)
   - Asks if you want a desktop shortcut
   - Asks if you want to run SIQspeak right away

**If anything fails**, the window will stay open and show you the error. You can screenshot it and report the issue.

### Step 4: You're Done

After setup, you can run SIQspeak anytime by:
- Double-clicking the **desktop shortcut** (if you created one), or
- Double-clicking `setup.bat` again and choosing "Run SIQspeak now"

A small floating pill will appear on your screen and a tray icon will show in the taskbar. You're ready to go.

## Usage

| Action | What happens |
|--------|-------------|
| **Hold** `Ctrl+Shift+Space` | Recording starts - pill expands with cyan animated dots |
| **Release** `Ctrl+Shift+Space` | Recording stops, transcription begins - dots turn white |
| Transcription completes | Text is typed into the window that was active when you started recording |
| **Hover** the idle pill | Shows transcription history panel |
| **Click copy icon** in history | Copies that transcription to clipboard |
| **Right-click** tray icon > Quit | Exit the app |

### Tray icon colors

- **Gray** - Idle, ready
- **Cyan** - Recording
- **Dark blue** - Transcribing

## Run at Startup (Optional)

To launch SIQspeak automatically when Windows starts:

1. Press `Win+R`, type `shell:startup`, press Enter
2. Create a shortcut in that folder with this target:

```
C:\path\to\SIQspeak\.venv\Scripts\pythonw.exe -m siqspeak
```

Using `pythonw.exe` (note the `w`) runs the app without a console window.

## Configuration

Settings are managed via the overlay UI. Constants live in `src/siqspeak/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `MODEL_NAME` | `"tiny"` | Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `SAMPLE_RATE` | `16000` | Audio sample rate in Hz |
| `HOTKEY` | `Ctrl+Shift+Space` | Hold-to-record hotkey |

Larger models are more accurate but slower. The `tiny` model works well for English dictation on most hardware.

| Model | Size | Relative Speed |
|-------|------|---------------|
| `tiny` | ~75 MB | Fastest |
| `base` | ~140 MB | Fast |
| `small` | ~460 MB | Moderate |
| `medium` | ~1.5 GB | Slow |
| `large-v3` | ~3 GB | Slowest |

## Troubleshooting

### Setup window closes immediately
Make sure you extracted the ZIP file first (don't run setup.bat from inside the ZIP). Right-click the ZIP > "Extract All..." > then open the extracted folder and run setup.bat from there.

### "Python was not found"
Python isn't installed or isn't in your PATH. Reinstall Python from [python.org](https://www.python.org/downloads/) and make sure to check **"Add Python to PATH"** during installation. Restart your computer after installing.

### "Failed to register hotkey" on startup
Another application is using `Ctrl+Shift+Space`. Close the conflicting app or change the hotkey constants in `src/siqspeak/config.py`.

### Model download fails
The speech model downloads from Hugging Face on first run (~75 MB). If it fails:
- Check your internet connection
- Try again later (Hugging Face may be temporarily slow)
- If you're behind a corporate firewall/proxy, you may need to download the model manually

### No audio / transcription is empty
- Check that your microphone is set as the default recording device in Windows Sound settings
- Try speaking louder or closer to the mic - recordings under 0.3 seconds are ignored

### Text doesn't appear in the target window
Some applications (admin-elevated windows, certain games) may not accept simulated keyboard input. Try a different target window.

## How It Works

1. Loads the Whisper model into memory at startup
2. Registers a global hotkey via the Win32 API
3. On hotkey press: opens the microphone and records audio chunks
4. On hotkey release: concatenates audio, runs Whisper inference
5. Restores focus to the original window and types the text via Unicode keyboard events

No clipboard is used for pasting - text is injected directly as keystrokes.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, code quality tools, and PR guidelines.

## License

[MIT](LICENSE) - Copyright (c) 2026 SIQstack
