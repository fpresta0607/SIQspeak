# SIQspeak

Local speech-to-text for Windows. Hold a hotkey, speak, release — your words are typed into the active window. No cloud, no API keys, 100% private.

Powered by OpenAI's [Whisper](https://github.com/openai/whisper) model running locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Features

- **Hold-to-talk** — Hold `Ctrl+Shift+Space` to record, release to transcribe
- **Auto-type** — Transcribed text is typed directly into whatever window was active
- **100% local** — Whisper runs on your CPU, nothing leaves your machine
- **System tray** — Runs quietly in the background, right-click to quit
- **Visual overlay** — Animated floating pill shows recording/transcribing status with audio-reactive dots
- **Transcription history** — Hover the idle pill to see recent transcriptions, click to copy
- **No API keys** — No accounts, no subscriptions, no internet required after setup

## Requirements

- **Windows 10 or 11**
- **Python 3.10+** — [Download from python.org](https://www.python.org/downloads/)
- **Microphone** — Any built-in or USB mic works

## Installation

### Quick Start

1. [Install Python 3.10+](https://www.python.org/downloads/) (check **"Add to PATH"**)
2. Clone or download this repo
3. Double-click **`setup.bat`**

That's it. The setup script creates the virtual environment, installs dependencies, and optionally creates a desktop shortcut.

On first run, the Whisper model (~75 MB for `tiny`) will download automatically. After that, no internet is needed.

### Manual Installation

<details>
<summary>Click to expand manual steps</summary>

#### 1. Install Python

Download Python from [python.org](https://www.python.org/downloads/) and run the installer.

> **Important:** Check the box that says **"Add Python to PATH"** during installation.

#### 2. Clone this repo

```bash
git clone https://github.com/fpresta0607/SIQspeak.git
cd SIQspeak
```

Or download and extract the ZIP from the GitHub releases page.

#### 3. Create a virtual environment

```bash
python -m venv .venv
```

#### 4. Activate the virtual environment

```bash
.venv\Scripts\activate
```

#### 5. Install dependencies

```bash
pip install -r requirements.txt
```

#### 6. Run

```bash
python dictate.py
```

A system tray icon will appear — you're ready to dictate.

</details>

## Usage

| Action | What happens |
|--------|-------------|
| **Hold** `Ctrl+Shift+Space` | Recording starts — pill expands with cyan animated dots |
| **Release** `Ctrl+Shift+Space` | Recording stops, transcription begins — dots turn white |
| Transcription completes | Text is typed into the window that was active when you started recording |
| **Hover** the idle pill | Shows transcription history panel |
| **Click copy icon** in history | Copies that transcription to clipboard |
| **Right-click** tray icon → Quit | Exit the app |

### Tray icon colors

- **Gray** — Idle, ready
- **Cyan** — Recording
- **Dark blue** — Transcribing

## Run at Startup (Optional)

To launch SIQspeak automatically when Windows starts:

1. Press `Win+R`, type `shell:startup`, press Enter
2. Create a shortcut in that folder with this target:

```
C:\path\to\SIQspeak\.venv\Scripts\pythonw.exe C:\path\to\SIQspeak\dictate.py
```

Using `pythonw.exe` (note the `w`) runs the app without a console window.

## Configuration

All settings are at the top of `dictate.py`:

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

### "Failed to register hotkey" on startup
Another application is using `Ctrl+Shift+Space`. Close the conflicting app or change the hotkey constants in `dictate.py`.

### No audio / transcription is empty
- Check that your microphone is set as the default recording device in Windows Sound settings
- Try speaking louder or closer to the mic — recordings under 0.3 seconds are ignored

### Model download fails
The model downloads from Hugging Face on first run. If you're behind a firewall or proxy, download may fail. Ensure you have internet access for the initial setup.

### Text doesn't appear in the target window
Some applications (admin-elevated windows, certain games) may not accept simulated keyboard input. Try a different target window.

## How It Works

Single-file architecture. The app:

1. Loads the Whisper model into memory at startup
2. Registers a global hotkey via the Win32 API
3. On hotkey press: opens the microphone and records audio chunks
4. On hotkey release: concatenates audio, runs Whisper inference on CPU
5. Restores focus to the original window and types the text via Unicode keyboard events

No clipboard is used for pasting — text is injected directly as keystrokes.

## License

[MIT](LICENSE) — Copyright (c) 2026 SIQstack
