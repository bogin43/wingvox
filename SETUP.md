# WingVox setup — after running install.sh

`install.sh` handles everything it can automatically. This guide covers the
few steps that only you can do — macOS requires an actual click from a human
in System Settings for these, so no script can do them for you.

**Prerequisites**: you're on an Apple Silicon Mac (M1/M2/M3/M4), and
`install.sh` finished without printing an error.

## 1. Microphone

WingVox needs to hear you.

1. Open **System Settings > Privacy & Security > Microphone**
2. Find the entry matching the exact path `install.sh` printed at the end
   (it'll look like a generic "Python" entry — match the exact path, not
   just the name, especially if there's more than one)
3. Make sure its toggle is **on**

Skip this and every dictation will say "Heard nothing" even when you're
speaking clearly.

## 2. Accessibility

WingVox needs this to detect your hotkey press and paste text into whatever
app you're using.

1. Open **System Settings > Privacy & Security > Accessibility**
2. Find the same Python entry, toggle it **on**
   (if it's not listed, click **+**, press **Cmd+Shift+G**, and paste the
   path from `install.sh`'s output)

Skip this and you'll see "Accessibility access not granted — hotkey & paste
won't work" the first time WingVox starts.

## 3. Input Monitoring

A separate permission (as of recent macOS versions) also required for the
global hotkey to work at all.

1. Open **System Settings > Privacy & Security > Input Monitoring**
2. Same as above — find or add the entry, toggle it **on**

Skip this and pressing the hotkey will do nothing at all — no error, no
overlay, just silence.

## After granting permissions

If WingVox was already running when you granted these, quit and relaunch it
(or just log out and back in — WingVox restarts automatically on login).
Toggling a permission for an already-running app usually doesn't take effect
until it restarts.

## How to verify it worked

Hold **Right Option**, say a sentence, release. You should see a small pill
near your cursor react to your voice, then briefly show a green checkmark
with your transcribed text once it pastes.

## Troubleshooting

| What you see | Likely cause |
|---|---|
| "Heard nothing" every time, even speaking clearly | Microphone permission not granted (step 1) |
| Nothing happens at all when you hold the hotkey — no pill, no sound | Input Monitoring not granted (step 3) |
| The pill shows recording/transcribing, but nothing gets pasted | Accessibility not granted (step 2) |
| "Accessibility access not granted" message on startup | Same as above (step 2) |
| "Ollama not running — will paste raw transcripts" | Run `brew services start ollama` |
| "Ollama model not pulled — will paste raw transcripts" | Run `ollama pull qwen2.5:3b` |
| "WingVox is already running" when trying to start it manually | It's already running via the background service — that's normal, no action needed |
| Text pastes but sounds too polished/reworded | Not expected — please report this, cleanup is meant to only fix filler words and punctuation |

## Where to get help

Ask in the Millionaire University community — mention you're using WingVox
and what step you're stuck on.

## Reference: other Whisper model sizes

WingVox ships with `whisper-large-v3-turbo` (~1.5GB), the best balance of
speed and accuracy. If you ever want to try a smaller model — for a slow
connection or an older Mac — these are the other options (edit
`WHISPER_REPO` in `flow.py`, prefixed with `mlx-community/`):

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
