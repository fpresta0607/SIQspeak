# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SIQspeak.

Bundles the app + Whisper tiny model into a single folder.
Run: pyinstaller siqspeak.spec
"""

import os
import sys
import site
from pathlib import Path

block_cipher = None

# ---------------------------------------------------------------------------
# Locate packages for data collection
# ---------------------------------------------------------------------------
def find_package(name):
    """Find a package's directory in site-packages."""
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        p = Path(sp) / name
        if p.exists():
            return str(p)
    # Fallback: import and use __file__
    mod = __import__(name)
    return str(Path(mod.__file__).parent)


# Collect ctranslate2 shared libraries
ct2_path = find_package("ctranslate2")

# Find the HuggingFace cached model
def find_hf_model(model_name="tiny"):
    """Locate the cached Whisper model directory."""
    from faster_whisper.utils import _MODELS
    from huggingface_hub import try_to_load_from_cache, scan_cache_dir
    
    repo_id = _MODELS.get(model_name)
    if not repo_id:
        raise RuntimeError(f"Unknown model: {model_name}")
    
    # Find the snapshot directory
    cache_info = scan_cache_dir()
    for repo in cache_info.repos:
        if repo.repo_id == repo_id:
            for revision in repo.revisions:
                return str(revision.snapshot_path)
    
    raise RuntimeError(f"Model {model_name} not found in HF cache. Run scripts/download_model.py first.")


model_dir = find_hf_model("tiny")

a = Analysis(
    ["src/siqspeak/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # App assets
        ("dictate.ico", "."),
        # Whisper model (bundled for offline use)
        (model_dir, "models/tiny"),
        # ctranslate2 shared libs
        (ct2_path, "ctranslate2"),
    ],
    hiddenimports=[
        "siqspeak",
        "siqspeak.app",
        "siqspeak.config",
        "siqspeak.hotkey",
        "siqspeak.state",
        "siqspeak.tray",
        "siqspeak.logging_setup",
        "siqspeak.model",
        "siqspeak.model.manager",
        "siqspeak.audio",
        "siqspeak.overlay",
        "siqspeak.interaction",
        "siqspeak.win32",
        "faster_whisper",
        "ctranslate2",
        "huggingface_hub",
        "sounddevice",
        "numpy",
        "pystray",
        "PIL",
        "PIL.Image",
        "pyperclip",
        "_sounddevice_data",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SIQspeak",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window (like pythonw)
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon="dictate.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SIQspeak",
)
