# Wingvox

**Website:** [bogin43.github.io/wingvox](https://bogin43.github.io/wingvox/)

Fully offline voice dictation. Hold the dictation hotkey (**Right Option** on
Mac, **Right Alt** on Windows), speak, release. Cleaned-up text is pasted
wherever your cursor is focused.

Pipeline: mic -> Whisper (mlx-whisper on Mac, faster-whisper on Windows) -> Ollama
qwen2.5:3b cleanup -> clipboard + paste.

> This is a personal project, shared as-is in case it's useful to others, not a
> polished product with official support. On Mac it requires **Microphone**,
> **Accessibility**, and **Input Monitoring** permissions (see below for why); on
> Windows, **Microphone** access and an antivirus that doesn't block global hotkeys.
> The installer will install Homebrew/Xcode Command Line Tools/Ollama (Mac) or
> winget/Ollama (Windows) if they're missing. Read the script before running it if
> you'd like to know exactly what it does. Use at your own risk. The Windows build
> isn't code-signed yet, so expect a SmartScreen warning on first launch.

## Get it

### Mac

Requires an Apple Silicon Mac (M1/M2/M3/M4). Open Terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/bogin43/wingvox/main/bootstrap.sh | bash
```

This clones the repo to `~/wingvox` and runs the installer. Prefer to see the
code before running anything? Clone it yourself instead:

```bash
git clone https://github.com/bogin43/wingvox.git ~/wingvox
cd ~/wingvox
./install.sh
```

Installs Homebrew/Ollama/Python as needed, builds `Wingvox.app`, and sets it up to
start automatically at login. Takes a few minutes, longer on a slow connection (the
Whisper model is ~1.5GB, the cleanup model another ~2GB — expect ~4GB of downloads
total on first run). Then see `SETUP.md` for the one-time macOS permission steps
it can't do for you.

Don't move the `~/wingvox` folder after installing — both the app and its
background service reference this exact location.

### Windows

Requires `winget` (ships with modern Windows 10/11; see [aka.ms/getwinget](https://aka.ms/getwinget)
if missing) and `git`. Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/bogin43/wingvox/main/bootstrap.ps1 | iex
```

This clones the repo to `%USERPROFILE%\wingvox` and runs the installer. Prefer to
see the code first? Clone it yourself instead:

```powershell
git clone https://github.com/bogin43/wingvox.git $env:USERPROFILE\wingvox
cd $env:USERPROFILE\wingvox
.\install.ps1
```

Installs Ollama/Python as needed, builds `Wingvox.exe`, and registers a Task
Scheduler entry so it starts automatically at login. The Whisper model
(`small.en` by default — see `SETUP.md` for other sizes) and the cleanup model
download on first run.

Don't move the `%USERPROFILE%\wingvox` folder after installing — the background
task references this exact location.

## Run it

### Mac

After `install.sh`, Wingvox starts automatically every login — nothing to run
manually. To restart it by hand (e.g. after editing `flow.py`/`overlay_mac.py`):

```bash
launchctl kickstart -k gui/$(id -u)/com.broganwilliams.wingvox
```

### Windows

After `install.ps1`, Wingvox starts automatically every login. To restart it by
hand:

```powershell
schtasks /end /tn Wingvox
schtasks /run /tn Wingvox
```

### Both platforms

A status pill near your cursor shows what it's doing: loading models on
startup, then Recording / Transcribing / Cleaning / a green check with the pasted text.
Warnings (Ollama down, transcription errors) show in orange. It never steals focus.
If Ollama is down, dictation still works; it pastes the raw transcript instead.
(On Windows, the pill is a solid dark capsule rather than translucent — stock
Tkinter has no true per-pixel transparency on Windows, only a colorkey.)

## Requirements

Handled automatically by the installer:

**Mac**
- Ollama running as a service, with `qwen2.5:3b` pulled
- Whisper weights cached at `~/.cache/huggingface` (downloaded once; works offline after)
- venv with mlx-whisper, sounddevice, pynput, requests, and the pyobjc framework bindings

**Windows**
- Ollama running, with `qwen2.5:3b` pulled
- Whisper weights (faster-whisper/CTranslate2 format) cached on first run; works offline after
- venv with faster-whisper, sounddevice, pynput, requests, pyperclip, pyinstaller

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

## Windows permissions & known limitations

There's no Windows equivalent of macOS's Accessibility/Input Monitoring gate —
the global hotkey and simulated paste work for a normal (non-elevated) process
with no extra setup. Two real limitations instead, neither of which is
something the app can request around:

- **Some antivirus/EDR software flags global low-level keyboard hooks as
  suspicious.** If the hotkey never fires, check your AV's activity log.
- **UIPI** (User Interface Privilege Isolation) blocks the simulated paste from
  reaching any window running elevated — Task Manager, an admin Command
  Prompt, some installers. Wingvox can't paste into those; it's an OS security
  boundary, not a bug.
- On some non-US keyboard layouts, physical Right Alt is reported as AltGr
  rather than alt_r — Wingvox listens for either, but if it still doesn't
  fire, try the other Alt key.

If dictation says "Heard nothing" every time, check Settings > Privacy & security
> Microphone.

## Custom vocabulary

Add one term per line to `dictionary.txt` (`~/wingvox/dictionary.txt` on Mac,
`%LOCALAPPDATA%\Wingvox\dictionary.txt` on Windows). Terms are fed to both
Whisper (spelling) and the cleanup LLM (capitalization). The installer seeds it
from `dictionary.default.txt` on first run only — your own edits are never
overwritten by re-running it.

## Mic selection

**Mac**: pinned to the built-in MacBook Air microphone by name (re-resolved on
every recording start, so it survives Bluetooth devices connecting/disconnecting).
To force a different one:

```bash
WINGVOX_INPUT_DEVICE="MacBook Air Microphone" ./venv/bin/python flow.py
```

**Windows**: no universal built-in-mic name to match, so it uses the system
default input device, preferring the WASAPI host API over PortAudio's default
(often MME, higher latency). Override with the same environment variable:

```powershell
$env:WINGVOX_INPUT_DEVICE = "Realtek"; .\venv\Scripts\python.exe flow.py
```

## Test individual stages

**Mac**
```bash
./venv/bin/python flow.py test-stt              # record 5s, print transcript
./venv/bin/python flow.py test-clean "um so uh hi"   # LLM cleanup only
./venv/bin/python flow.py test-inject "hello"   # pastes into focused field after 3s
```

**Windows**
```powershell
.\venv\Scripts\python.exe flow.py test-stt
.\venv\Scripts\python.exe flow.py test-clean "um so uh hi"
.\venv\Scripts\python.exe flow.py test-inject "hello"
```

## Measured performance (M4 Air, 16GB)

- 7.4s of speech: STT 1.15s + cleanup 1.0s = ~2.3s release-to-text
- Verified working with Wi-Fi off

Windows performance depends heavily on the CPU (and GPU, if you have an NVIDIA
card) — no benchmark numbers yet. The default `small.en` model is chosen to be
usable on CPU-only laptops; set `WINGVOX_WHISPER_MODEL` to a bigger model if
you have a CUDA GPU (see `SETUP.md`).
