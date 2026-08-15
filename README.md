# Wingvox

**Website:** [bogin43.github.io/wingvox](https://bogin43.github.io/wingvox/)

Fully offline voice dictation. Hold the dictation hotkey (**Right Option** on
Mac, **Right Alt** on Windows), speak, release. Cleaned-up text is pasted
wherever your cursor is focused.

Pipeline: mic -> Whisper (mlx-whisper on Mac, faster-whisper on Windows) -> Ollama
qwen2.5:3b cleanup -> clipboard + paste.

> This is a personal project, shared as-is in case it's useful to others, not a
> polished product with official support. On Mac it requires **Microphone** and
> **Accessibility** permissions (see below for why); on
> Windows, **Microphone** access and an antivirus that doesn't block global hotkeys.
> The installer will install Homebrew/Xcode Command Line Tools/Ollama (Mac) or
> winget/Ollama (Windows) if they're missing. Read the script before running it if
> you'd like to know exactly what it does. Use at your own risk. The Windows build
> isn't code-signed yet, so expect a SmartScreen warning on first launch.

## Get it

### Mac

Requires an Apple Silicon Mac (M1/M2/M3/M4) running macOS 14 Sonoma or newer.
Intel Macs aren't supported: the speech engine (mlx) is Apple Silicon only.
Open Terminal and run:

```bash
curl -fsSL https://bogin43.github.io/wingvox/mac | bash
```

This clones the repo to `~/wingvox` and runs the installer. Prefer to see the
code before running anything? Clone it yourself instead:

```bash
git clone https://github.com/bogin43/wingvox.git ~/wingvox
cd ~/wingvox
./install.sh
```

Installs Homebrew/Ollama/Python as needed, builds `Wingvox.app`, and sets it up to
start automatically at login. Takes a few minutes, longer on a slow connection: the
speech model is ~0.5GB and the cleanup model another ~1.8GB, so budget **~2.6GB**
for everything. Then see `SETUP.md` for the one-time macOS permission steps it
can't do for you.

**Smaller install.** The cleanup model is most of that download. To skip it:

```bash
WINGVOX_LITE=1 bash -c "$(curl -fsSL https://bogin43.github.io/wingvox/mac)"
```

That brings the install down to about **0.9GB**. Dictation still works — Whisper
already produces punctuated text — but you lose the cleanup pass that strips
"um" and "so like" and tidies sentence boundaries. Re-run the normal installer
any time to add it.

Don't move the `~/wingvox` folder after installing — both the app and its
background service reference this exact location.

To remove it, run `./uninstall.sh` from the Wingvox folder. It stops Wingvox,
removes the login service and the built app, and asks before touching your
glossary. Homebrew, Python, Ollama and the models are left alone, with the
commands to remove those printed at the end if you want them gone too.

### Windows

Requires `winget` (ships with modern Windows 10/11; see [aka.ms/getwinget](https://aka.ms/getwinget)
if missing) and `git`. Open PowerShell and run:

```powershell
irm https://bogin43.github.io/wingvox/windows | iex
```

This clones the repo to `%USERPROFILE%\wingvox` and runs the installer. Prefer to
see the code first? Clone it yourself instead:

```powershell
git clone https://github.com/bogin43/wingvox.git $env:USERPROFILE\wingvox
cd $env:USERPROFILE\wingvox
.\install.ps1
```

Installs Ollama/Python as needed, downloads both models, builds `Wingvox.exe`,
and registers a Task Scheduler entry so it starts automatically at login.
Takes a few minutes, longer on a slow connection: the Whisper model
(`small.en` by default — see `SETUP.md` for other sizes) is ~1GB and the
cleanup model another ~2GB. Budget **~3.5GB of disk** for everything
(models, the Python environment, and the built app).

Don't move the `%USERPROFILE%\wingvox` folder after installing — the background
task references this exact location.

To update later, re-run the same one-liner: it pulls the latest code and
re-installs over the top, keeping your glossary and corrections.

To remove it, run `.\uninstall.ps1` from the Wingvox folder.

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

**Turning it off for a while.** If Wingvox is competing for the hotkey or the
mic with something else — a VM, a game, screen-sharing software, another
dictation tool — double-click **`wingvox-off.cmd`** in the Wingvox folder. It
stays off (including across reboots) until you double-click
**`wingvox-on.cmd`**. Neither one uninstalls anything.

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

System Settings > Privacy & Security: grant **Microphone** and **Accessibility**
to **Wingvox**. If dictation silently does nothing, or the hotkey works but paste
doesn't land, this is why. If it isn't listed, add it with `+` > Cmd+Shift+G >
`~/wingvox/Wingvox.app`.

**Input Monitoring** is also required for the hotkey, but Accessibility normally
satisfies it — an Accessibility-trusted app is allowed to listen for key presses,
and Wingvox won't appear in that list at all. Only grant it explicitly if the
hotkey produces no response whatsoever.

macOS attributes these to the `Wingvox.app` bundle the LaunchAgent runs, not to
the Python interpreter inside it — so there's nothing to re-grant when Homebrew
bumps its Python version. (Earlier versions of this guide said to grant a
"Python" entry instead. That was left over from before the app bundle existed;
following it now grants permission to something that isn't what runs.)

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
