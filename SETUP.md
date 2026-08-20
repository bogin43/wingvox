# Wingvox setup — after running the installer

The installer (`install.sh` on Mac, `install.ps1` on Windows) handles
everything it can automatically. This guide covers the few steps that only
you can do — the OS requires an actual click from a human for these, so no
script can do them for you.

Jump to: [Mac](#mac-setup) · [Windows](#windows-setup)

## Mac setup

**Prerequisites**: you're on a Mac (Apple Silicon or Intel), and
`install.sh` finished without printing an error.

### 1. Microphone

Wingvox needs to hear you.

1. Open **System Settings > Privacy & Security > Microphone**
2. Find **Wingvox** in the list
3. Make sure its toggle is **on**

Skip this and every dictation will say "Heard nothing" even when you're
speaking clearly.

### 2. Accessibility

Wingvox needs this to detect your hotkey press and paste text into whatever
app you're using.

1. Open **System Settings > Privacy & Security > Accessibility**
2. Find **Wingvox**, toggle it **on**

Skip this and you'll see "Accessibility access not granted — hotkey & paste
won't work" the first time Wingvox starts.

### 3. Input Monitoring — usually nothing to do

The global hotkey needs this, but granting Accessibility above normally
satisfies it too: macOS treats an Accessibility-trusted app as allowed to
listen for key presses, and Wingvox won't even appear in this list.

Only if pressing the hotkey does nothing at all — no pill, no sound, no
error — open **System Settings > Privacy & Security > Input Monitoring**
and turn **Wingvox** on there as well (adding it with **+** if needed).

**If Wingvox isn't listed** in one of them, click **+**, press
**Cmd+Shift+G**, and paste `~/wingvox/Wingvox.app` (the exact path is
printed at the end of the installer).

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

Wingvox ships with `whisper-large-v3-turbo-q4` (~0.5GB), a 4-bit build of
the turbo model. It matched the full-precision version on every test clip
here while being a third of the size. If you ever want to try a smaller model — for a slow
connection or an older Mac — these are the other options (set `WINGVOX_WHISPER_REPO`, prefixed with `mlx-community/`):

| Model | Approx. size | Accuracy |
|---|---|---|
| `whisper-tiny` | ~75MB | Rough — fine for short commands, not real dictation |
| `whisper-base` | ~145MB | Still rough for natural speech |
| `whisper-small` | ~500MB | Usable, a clear step down from turbo |
| `whisper-medium` | ~1.5GB | Similar size to full turbo, similar-ish accuracy |
| `whisper-large-v3-turbo-q4` (default) | ~0.5GB | What's used out of the box |
| `whisper-large-v3-turbo` | ~1.6GB | Full precision. Matched q4 on every clip tested here |
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

### Turning Wingvox off and back on

You don't need to uninstall it just to get it out of the way for a while.
In the Wingvox folder there are two scripts you can double-click:

| Script | What it does |
|---|---|
| `wingvox-off.cmd` | Stops Wingvox and keeps it from starting again, even after a reboot |
| `wingvox-on.cmd` | Turns it back on and starts it immediately |

Useful when something else needs the same hotkey or the microphone — a virtual
machine, a game, screen-sharing software, or another dictation tool.

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

## Supported languages

Wingvox dictates in English by default. To switch, from the Wingvox folder:

```bash
cd ~/wingvox && ./set-language.sh fr
```

Any of the 100 codes below works. Flemish has no separate code of its own --
it's transcribed as Dutch (`nl`), the same written standard as Netherlands
Dutch. On Windows, the default speech model is English-only regardless of
this setting; switching languages there also needs
`WINGVOX_WHISPER_MODEL=small` set by hand.

| Language | Code | | Language | Code | | Language | Code |
|---|---|---|---|---|---|---|---|
| Afrikaans | `af` | | Albanian | `sq` | | Amharic | `am` |
| Arabic | `ar` | | Armenian | `hy` | | Assamese | `as` |
| Azerbaijani | `az` | | Bashkir | `ba` | | Basque | `eu` |
| Belarusian | `be` | | Bengali | `bn` | | Bosnian | `bs` |
| Breton | `br` | | Bulgarian | `bg` | | Cantonese | `yue` |
| Catalan | `ca` | | Chinese | `zh` | | Croatian | `hr` |
| Czech | `cs` | | Danish | `da` | | Dutch | `nl` |
| English | `en` | | Estonian | `et` | | Faroese | `fo` |
| Finnish | `fi` | | French | `fr` | | Galician | `gl` |
| Georgian | `ka` | | German | `de` | | Greek | `el` |
| Gujarati | `gu` | | Haitian Creole | `ht` | | Hausa | `ha` |
| Hawaiian | `haw` | | Hebrew | `he` | | Hindi | `hi` |
| Hungarian | `hu` | | Icelandic | `is` | | Indonesian | `id` |
| Italian | `it` | | Japanese | `ja` | | Javanese | `jw` |
| Kannada | `kn` | | Kazakh | `kk` | | Khmer | `km` |
| Korean | `ko` | | Lao | `lo` | | Latin | `la` |
| Latvian | `lv` | | Lingala | `ln` | | Lithuanian | `lt` |
| Luxembourgish | `lb` | | Macedonian | `mk` | | Malagasy | `mg` |
| Malay | `ms` | | Malayalam | `ml` | | Maltese | `mt` |
| Maori | `mi` | | Marathi | `mr` | | Mongolian | `mn` |
| Myanmar | `my` | | Nepali | `ne` | | Norwegian | `no` |
| Nynorsk | `nn` | | Occitan | `oc` | | Pashto | `ps` |
| Persian | `fa` | | Polish | `pl` | | Portuguese | `pt` |
| Punjabi | `pa` | | Romanian | `ro` | | Russian | `ru` |
| Sanskrit | `sa` | | Serbian | `sr` | | Shona | `sn` |
| Sindhi | `sd` | | Sinhala | `si` | | Slovak | `sk` |
| Slovenian | `sl` | | Somali | `so` | | Spanish | `es` |
| Sundanese | `su` | | Swahili | `sw` | | Swedish | `sv` |
| Tagalog | `tl` | | Tajik | `tg` | | Tamil | `ta` |
| Tatar | `tt` | | Telugu | `te` | | Thai | `th` |
| Tibetan | `bo` | | Turkish | `tr` | | Turkmen | `tk` |
| Ukrainian | `uk` | | Urdu | `ur` | | Uzbek | `uz` |
| Vietnamese | `vi` | | Welsh | `cy` | | Yiddish | `yi` |
| Yoruba | `yo` | |  |  | |  |  |

## Updates and notices

Wingvox checks once at startup whether a newer version has been published. It
asks GitHub a single question — "is there a newer commit?" — and sends nothing
about you or about anything you've dictated. It never installs an update by
itself.

If there's one available, the status pill says so. To take it, on Mac:

```bash
cd ~/wingvox && ./update.sh
```

That shows you what changed, pulls it, and restarts Wingvox. Most updates need
nothing else: the app runs `flow.py` straight out of that folder, so new code
takes effect on restart. If an update also changes the Python dependencies or
the speech model, `update.sh` says so and points you at the installer, since a
restart alone can't pick those up.

To check by hand at any time:

```bash
~/wingvox/venv/bin/python ~/wingvox/flow.py check-update
```

Occasionally an update carries something you should actually read — a change to
what Wingvox does with your data, or behavior that works differently than
before. Those appear as a dialog the first time you start the new version, and
Wingvox waits for you to acknowledge it before it starts listening for the
hotkey. It asks once per notice, not once per launch. The full text lives in
`NOTICE.md` in the Wingvox folder if you want to re-read it later.

## Where to get help

Ask in the Millionaire University community — mention you're using Wingvox
and what step you're stuck on.
