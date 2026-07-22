# Wingvox setup — after running the installer

The installer (`install.sh` on Mac, `install.ps1` on Windows) handles
everything it can automatically. This guide covers the few steps that only
you can do — the OS requires an actual click from a human for these, so no
script can do them for you.

Jump to: [Mac](#mac-setup) · [Windows](#windows-setup)

## Mac setup

**Prerequisites**: you're on an Apple Silicon Mac (M1/M2/M3/M4), and
`install.sh` finished without printing an error.

### 1. Microphone

Wingvox needs to hear you.

1. Open **System Settings > Privacy & Security > Microphone**
2. Find the entry matching the exact path `install.sh` printed at the end
   (it'll look like a generic "Python" entry — match the exact path, not
   just the name, especially if there's more than one)
3. Make sure its toggle is **on**

Skip this and every dictation will say "Heard nothing" even when you're
speaking clearly.

### 2. Accessibility

Wingvox needs this to detect your hotkey press and paste text into whatever
app you're using.

1. Open **System Settings > Privacy & Security > Accessibility**
2. Find the same Python entry, toggle it **on**
   (if it's not listed, click **+**, press **Cmd+Shift+G**, and paste the
   path from `install.sh`'s output)

Skip this and you'll see "Accessibility access not granted — hotkey & paste
won't work" the first time Wingvox starts.

### 3. Input Monitoring

A separate permission (as of recent macOS versions) also required for the
global hotkey to work at all.

1. Open **System Settings > Privacy & Security > Input Monitoring**
2. Same as above — find or add the entry, toggle it **on**

Skip this and pressing the hotkey will do nothing at all — no error, no
overlay, just silence.

### After granting permissions

If Wingvox was already running when you granted these, quit and relaunch it
(or just log out and back in — Wingvox restarts automatically on login).
Toggling a permission for an already-running app usually doesn't take effect
until it restarts.

### How to verify it worked (Mac)

Hold **Right Option**, say a sentence, release. You should see a small pill
near your cursor react to your voice, then briefly show a green checkmark
with your transcribed text once it pastes.

### Troubleshooting (Mac)

| What you see | Likely cause |
|---|---|
| "Heard nothing" every time, even speaking clearly | Microphone permission not granted (step 1) |
| Nothing happens at all when you hold the hotkey — no pill, no sound | Input Monitoring not granted (step 3) |
| The pill shows recording/transcribing, but nothing gets pasted | Accessibility not granted (step 2) |
| "Accessibility access not granted" message on startup | Same as above (step 2) |
| "Ollama not running — will paste raw transcripts" | Run `brew services start ollama` |
| "Ollama model not pulled — will paste raw transcripts" | Run `ollama pull qwen2.5:3b` |
| "Wingvox is already running" when trying to start it manually | It's already running via the background service — that's normal, no action needed |
| Text pastes but sounds too polished/reworded | Not expected — please report this, cleanup is meant to only fix filler words and punctuation |

### Reference: other Whisper model sizes (Mac)

Wingvox ships with `whisper-large-v3-turbo` (~1.5GB), the best balance of
speed and accuracy. If you ever want to try a smaller model — for a slow
connection or an older Mac — these are the other options (edit
`WHISPER_REPO` in `stt_mac.py`, prefixed with `mlx-community/`):

| Model | Approx. size | Accuracy |
|---|---|---|
| `whisper-tiny` | ~75MB | Rough — fine for short commands, not real dictation |
| `whisper-base` | ~145MB | Still rough for natural speech |
| `whisper-small` | ~500MB | Usable, a clear step down from turbo |
| `whisper-medium` | ~1.5GB | Similar size to turbo, similar-ish accuracy |
| `whisper-large-v3-turbo` (default) | ~1.5GB | Best balance — what's used out of the box |
| `whisper-large-v3` | ~2.9GB | Marginally better than turbo, slower, bigger download |

This isn't something you need to change — just here in case it's useful
later.

## Windows setup

**Prerequisites**: `install.ps1` finished without printing an error.

### 1. Microphone

Wingvox needs to hear you. There's no Windows API to trigger the consent
prompt the way macOS has — if the first launch can't get mic access, Wingvox
opens **Settings > Privacy & security > Microphone** for you. Find "Wingvox"
(or the path `install.ps1` printed) and make sure it's allowed.

Skip this and every dictation will say "Heard nothing" even when you're
speaking clearly.

### 2. SmartScreen

The Windows build isn't code-signed yet (no Apple-Developer-style certificate
for Windows either), so the first launch will likely show:

> "Windows protected your PC"

Click **More info**, then **Run anyway**. This is expected — it's not a sign
anything is wrong, just what an unsigned .exe from a new publisher looks like.

### 3. Antivirus / global hotkey

Some antivirus and EDR software flags global low-level keyboard hooks (how
Wingvox detects the hotkey) as suspicious. If pressing the hotkey does
nothing at all — no pill, no sound — check your AV's activity/quarantine log
and allow Wingvox if it's listed there.

### How to verify it worked (Windows)

Hold **Right Alt**, say a sentence, release. You should see a small pill near
your cursor react to your voice, then briefly show a green checkmark with
your transcribed text once it pastes. (The pill is a solid dark capsule
rather than translucent — a Tkinter/Windows limitation, not a bug.)

### Troubleshooting (Windows)

| What you see | Likely cause |
|---|---|
| "Heard nothing" every time, even speaking clearly | Microphone permission not granted (step 1) |
| Nothing happens at all when you hold the hotkey — no pill, no sound | Antivirus/EDR blocking the global keyboard hook (step 3), or an international keyboard layout reporting Right Alt as AltGr — try the other Alt key |
| The pill shows recording/transcribing, but nothing gets pasted | The focused window is running as Administrator — Windows' UIPI blocks simulated input into elevated windows; this can't be worked around |
| "Ollama not running — will paste raw transcripts" | Launch the Ollama app, or run `ollama serve` |
| "Ollama model not pulled — will paste raw transcripts" | Run `ollama pull qwen2.5:3b` |
| "Wingvox is already running" when trying to start it manually | It's already running via the scheduled task — that's normal, no action needed |
| Text pastes but sounds too polished/reworded | Not expected — please report this, cleanup is meant to only fix filler words and punctuation |
| Transcription is noticeably less accurate than the website's demo | Expected on CPU-only machines — Windows defaults to the smaller `small.en` model for speed; see below to use a bigger one if you have a CUDA GPU |

### Reference: other Whisper model sizes (Windows)

Wingvox defaults to `small.en`, chosen to stay usable on a CPU-only laptop.
Override with the `WINGVOX_WHISPER_MODEL` environment variable before
launching (or set it permanently via Settings > System > Advanced system
settings > Environment Variables):

| Model | Notes |
|---|---|
| `tiny.en` | Fastest, roughest — short commands only |
| `base.en` | Still rough for natural speech |
| `small.en` (default) | Usable on CPU, reasonable latency |
| `medium.en` | Better accuracy, noticeably slower on CPU |
| `large-v3` | Best accuracy — only comfortable with a CUDA GPU |
| `distil-large-v3` | Near-`large-v3` accuracy, faster — a good pick if you have a GPU but want lower latency |

`device`/`compute_type` are set to `"auto"`, so a CUDA GPU is used
automatically if present; otherwise it falls back to CPU with int8 quantization.

## Where to get help

Ask in the Millionaire University community — mention you're using Wingvox
and what step you're stuck on.
