# WingVox

Local, offline voice dictation for macOS. Hold **Right Option**, speak, release. Cleaned-up text is pasted into whatever app has focus. 100% offline.

Pipeline: mic -> mlx-whisper (large-v3-turbo) -> Ollama qwen2.5:3b cleanup -> clipboard + Cmd+V.

> This is a personal project, shared as-is in case it's useful to others, not a
> polished product with official support. It requires **Microphone**,
> **Accessibility**, and **Input Monitoring** permissions (see below for why), and
> `install.sh` will install Homebrew/Xcode Command Line Tools/Ollama on your Mac if
> they're missing. Read the script before running it if you'd like to know exactly
> what it does. Use at your own risk.

## Get it

Requires an Apple Silicon Mac (M1/M2/M3/M4). Open Terminal and run:

```bash
git clone https://github.com/bogin43/wingvox.git ~/wingvox
cd ~/wingvox
./install.sh
```

Installs Homebrew/Ollama/Python as needed, builds `WingVox.app`, and sets it up to
start automatically at login. Takes a few minutes, longer on a slow connection (the
Whisper model is ~1.5GB, the cleanup model another ~2GB — expect ~4GB of downloads
total on first run). Then see `SETUP.md` for the one-time macOS permission steps
it can't do for you.

Don't move the `~/wingvox` folder after installing — both the app and its
background service reference this exact location.

## Run it

After `install.sh`, WingVox starts automatically every login — nothing to run
manually. To restart it by hand (e.g. after editing `flow.py`/`overlay.py`):

```bash
launchctl kickstart -k gui/$(id -u)/com.broganwilliams.wingvox
```

A status pill near your cursor shows what it's doing: loading models on
startup, then Recording / Transcribing / Cleaning / a green check with the pasted text.
Warnings (Ollama down, transcription errors) show in orange. It never steals focus.
If Ollama is down, dictation still works; it pastes the raw transcript instead.

## Requirements

Handled automatically by `install.sh`:

- Ollama running as a service, with `qwen2.5:3b` pulled
- Whisper weights cached at `~/.cache/huggingface` (downloaded once; works offline after)
- venv with mlx-whisper, sounddevice, pynput, requests, and the pyobjc framework bindings

## macOS permissions

System Settings > Privacy & Security: grant **Microphone**, **Accessibility**, and
**Input Monitoring** to the actual Python.app binary the venv runs
(`venv/bin/python` resolves to something like
`/opt/homebrew/Cellar/python@3.12/<version>/Frameworks/Python.framework/Versions/3.12/Resources/Python.app` —
check with `./venv/bin/python -c "import sys; print(sys.executable)"`).
If dictation silently does nothing, or the hotkey works but paste doesn't land, this is why.
If Homebrew has multiple Python versions installed, there may be more than one "Python" entry
in these lists with the same generic name/icon — make sure the one that's toggled on actually
points at this exact path (remove and re-add via `+` > Cmd+Shift+G if unsure).

## Custom vocabulary

Add one term per line to `dictionary.txt`. Terms are fed to both Whisper (spelling)
and the cleanup LLM (capitalization). `install.sh` seeds it from
`dictionary.default.txt` on first run only — your own edits are never overwritten
by re-running the installer.

## Mic selection

Pinned to the built-in MacBook Air microphone by name (re-resolved on every recording
start, so it survives Bluetooth devices connecting/disconnecting). To force a different one:

```bash
WINGVOX_INPUT_DEVICE="MacBook Air Microphone" ./venv/bin/python flow.py
```

## Test individual stages

```bash
./venv/bin/python flow.py test-stt              # record 5s, print transcript
./venv/bin/python flow.py test-clean "um so uh hi"   # LLM cleanup only
./venv/bin/python flow.py test-inject "hello"   # pastes into focused field after 3s
```

## Measured performance (M4 Air, 16GB)

- 7.4s of speech: STT 1.15s + cleanup 1.0s = ~2.3s release-to-text
- Verified working with Wi-Fi off
