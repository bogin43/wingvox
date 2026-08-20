#!/bin/bash
# Wingvox installer: sets up everything needed to run Wingvox on this Mac,
# building the app locally rather than shipping a pre-built binary (a
# pre-built .app would be rejected by Gatekeeper without a paid Apple
# Developer signing certificate, and mlx's Metal shader bundling isn't
# reliable across relocated machines — building fresh here avoids both).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

step() { echo; echo "==> $1"; }

# The cleanup-model download runs in the background from step 5 onward. If
# the install dies before step 9b collects it (a failed build, a Ctrl-C),
# don't leave a detached multi-gigabyte download running with nothing left
# to report to.
cleanup_bg() {
    if [[ -n "${PULL_PID:-}" ]] && kill -0 "$PULL_PID" 2>/dev/null; then
        kill "$PULL_PID" 2>/dev/null || true
        # Reap it, or bash prints its own "Terminated: 15" line on the way
        # out and the real error scrolls off behind job-control noise.
        wait "$PULL_PID" 2>/dev/null || true
    fi
    rm -f "${PULL_LOG:-}" 2>/dev/null || true
}
trap cleanup_bg EXIT

step "Installing Wingvox from: $REPO_DIR"
echo "    This location is now permanent — the app and its background"
echo "    service both reference this exact folder path. Don't move it"
echo "    after install without re-running this script."

# ---------- 1. Mac architecture ----------
# Determines which speech-engine path the rest of this script (and
# requirements.txt) takes: mlx on Apple Silicon, faster-whisper/CTranslate2
# on Intel. Exported so later steps don't re-run `uname -m` and can't get out
# of sync with this decision.
step "Checking Mac architecture"
MAC_ARCH="$(uname -m)"
if [[ "$MAC_ARCH" == "arm64" ]]; then
    echo "    OK — Apple Silicon detected."
elif [[ "$MAC_ARCH" == "x86_64" ]]; then
    echo "    OK — Intel Mac detected (using the faster-whisper speech engine)."
else
    echo "Wingvox requires an Apple Silicon or Intel Mac." >&2
    echo "This Mac reports '$MAC_ARCH', which isn't either." >&2
    exit 1
fi
export MAC_ARCH

# ---------- 1b. macOS version ----------
# mlx publishes arm64 wheels tagged macosx_14_0 and up, so Apple Silicon
# needs macOS 14+. On macOS 13 (Ventura) and older, pip doesn't fail -- it
# quietly walks back to mlx 0.29.3, the last release with a 13.0 wheel, which
# current mlx-whisper is not built against. The install then "succeeds" and
# Wingvox breaks at the first dictation, deep inside a model load, with an
# error nobody could trace back to their macOS version. Check it here where
# the message can say what's actually wrong.
#
# Intel Macs have a lower floor: their dependencies (ctranslate2 for speech,
# pyobjc for permissions) publish wheels back to macOS 11 and 10.13
# respectively. Since old Intel hardware is frequently stuck below macOS 14
# and can't upgrade further, holding Intel to the same 14+ floor as Apple
# Silicon would exclude most of the audience this path exists for.
step "Checking macOS version"
MACOS_VER="$(sw_vers -productVersion)"
MACOS_MAJOR="${MACOS_VER%%.*}"
MIN_MACOS=14
[[ "$MAC_ARCH" == "x86_64" ]] && MIN_MACOS=11
if [[ "$MACOS_MAJOR" -lt "$MIN_MACOS" ]]; then
    echo "Wingvox needs macOS $MIN_MACOS or newer on this Mac. This one is on $MACOS_VER." >&2
    echo >&2
    if [[ "$MAC_ARCH" == "arm64" ]]; then
        echo "The speech engine (mlx) publishes no build for this version of macOS." >&2
    else
        echo "The speech engine (faster-whisper) and Wingvox's permission handling" >&2
        echo "publish no build for this version of macOS." >&2
    fi
    echo "Updating in System Settings > General > Software Update is the only fix." >&2
    exit 1
fi
echo "    OK — macOS $MACOS_VER."
if [[ "$MAC_ARCH" == "x86_64" && "$MACOS_MAJOR" -lt 14 ]]; then
    echo "    Note: Homebrew may not have a prebuilt python@3.12 for this"
    echo "    macOS version and will compile it from source instead — the"
    echo "    first install will take longer than usual."
fi

# ---------- 2. Xcode Command Line Tools ----------
step "Checking for Xcode Command Line Tools"
if ! xcode-select -p &>/dev/null; then
    echo "    Not found — opening Apple's installer dialog."
    xcode-select --install 2>/dev/null || true
    echo
    echo "    A macOS dialog just opened. Click Install and accept the"
    echo "    licence; this script waits and carries on by itself."
    echo -n "    Waiting"
    # Previously this exited here and told the user to "re-run this script
    # (./install.sh)" -- but the one-line installer runs from the user's
    # home directory, where ./install.sh doesn't exist, so that instruction
    # just failed. Wait the dialog out instead; there's nothing the user
    # needs to do afterwards.
    for _ in $(seq 1 360); do   # up to ~60 min; the download is large
        xcode-select -p &>/dev/null && break
        echo -n "."
        sleep 10
    done
    echo
    if ! xcode-select -p &>/dev/null; then
        echo "Command Line Tools still aren't installed." >&2
        echo "Finish the dialog, then run this to pick up where it left off:" >&2
        echo "  $REPO_DIR/install.sh" >&2
        exit 1
    fi
    echo "    OK — Command Line Tools installed."
else
    echo "    OK — already installed."
fi

# ---------- 3. Homebrew ----------
step "Checking for Homebrew"
if ! command -v brew &>/dev/null; then
    echo "    Not found — installing Homebrew (you may be prompted for your password)."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi
echo "    OK — Homebrew available at $(command -v brew)."

# ---------- 4. Python and Ollama ----------
# On Apple Silicon both come from Homebrew, in a single brew call (one
# dependency-resolution pass, bottles fetched concurrently).
#
# On Intel, Python comes from uv instead. Homebrew announced in its 6.0.0
# release (2026-06-11) that Intel macOS drops to Tier 3 support starting
# September 2026 -- no more prebuilt bottles, source-compile only -- and
# loses support entirely in September 2027
# (https://brew.sh/2026/06/11/homebrew-6.0.0/). Tying Wingvox's Intel install
# to python@3.12's Homebrew bottle would put it on that same expiration
# date. uv ships its own standalone CPython builds (python-build-standalone),
# independent of Homebrew's architecture support, so this sidesteps the
# whole timeline. Ollama still comes from Homebrew on both arches for now --
# it's on the same eventual Intel deadline as any other formula, but
# replacing it isn't in scope here; revisit if/when Homebrew's Tier 3 cutoff
# actually breaks it.
step "Checking for Python and Ollama"

if [[ "$MAC_ARCH" == "arm64" ]]; then
    BREW_WANTED=()
    brew list python@3.12 &>/dev/null || BREW_WANTED+=(python@3.12)
    if [[ "${WINGVOX_LITE:-}" != "1" ]]; then
        brew list ollama &>/dev/null || BREW_WANTED+=(ollama)
    fi
    if [[ ${#BREW_WANTED[@]} -gt 0 ]]; then
        echo "    Installing: ${BREW_WANTED[*]}"
        brew install "${BREW_WANTED[@]}"
    else
        echo "    OK — both already installed."
    fi
    PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
else
    if ! command -v uv &>/dev/null; then
        echo "    Installing uv (a standalone Python installer, not tied to Homebrew)…"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
    echo "    Installing Python 3.12 via uv…"
    uv python install 3.12 -q
    PYTHON_BIN="$(uv python find 3.12)"

    if [[ "${WINGVOX_LITE:-}" != "1" ]]; then
        if ! brew list ollama &>/dev/null; then
            echo "    Installing: ollama"
            brew install ollama
        else
            echo "    OK — ollama already installed."
        fi
    fi
fi
echo "    Using $PYTHON_BIN"

# ---------- 5 & 6. Ollama and the cleanup model ----------
# WINGVOX_LITE=1 skips both. The cleanup model is 1.8GB of the ~2.6GB
# install, so leaving it out is the difference between a ~0.9GB download and
# a ~2.6GB one. Dictation still works: Whisper already produces punctuated
# text, and flow.py falls back to pasting the raw transcript whenever the
# cleanup step is unavailable. What you lose is filler removal ("um", "so
# like", false starts) and the tidier sentence boundaries.
if [[ "${WINGVOX_LITE:-}" == "1" ]]; then
    step "Skipping Ollama (WINGVOX_LITE=1)"
    echo "    Dictation will paste raw transcripts, without the cleanup pass."
    echo "    To add it later, re-run this installer without WINGVOX_LITE."
else
    step "Starting Ollama"
    brew services start ollama &>/dev/null || true
    echo -n "    Waiting for Ollama to come up"
    for i in $(seq 1 20); do
        if curl -s -o /dev/null http://127.0.0.1:11434/api/version; then
            echo " — ready."
            break
        fi
        echo -n "."
        sleep 1
        if [[ "$i" == 20 ]]; then
            echo
            echo "Ollama didn't come up after 20s. Try 'brew services restart ollama'" >&2
            echo "and re-run this script." >&2
            exit 1
        fi
    done

    # The 1.8GB cleanup model is the longest single step in the install and
    # nothing between here and the LaunchAgent needs it, so it runs in the
    # background while the venv, the Whisper download and the app build all
    # proceed. Collected at step 9b below. Output goes to a log rather than
    # the terminal: two progress bars writing to the same screen is a mess,
    # and the failure text is more useful shown in one piece at the end.
    step "Pulling the qwen2.5:3b cleanup model in the background (1.8GB)"
    PULL_LOG="$(mktemp)"
    ollama pull qwen2.5:3b >"$PULL_LOG" 2>&1 &
    PULL_PID=$!
    echo "    Started — the rest of the install continues while it downloads."
fi

# ---------- 7. Python virtual environment ----------
step "Setting up the Python environment"
if [[ ! -d "$REPO_DIR/venv" ]]; then
    "$PYTHON_BIN" -m venv "$REPO_DIR/venv"
    echo "    Created venv."
else
    echo "    venv already exists, reusing it."
fi
VENV_PY="$REPO_DIR/venv/bin/python"

step "Installing Python dependencies"
"$VENV_PY" -m pip install --upgrade pip -q
"$VENV_PY" -m pip install -r requirements.txt -q
# mlx-whisper on its own, with --no-deps. Its declared dependencies include
# torch, llvmlite, scipy, numba, sympy and networkx: ~176MB that nothing in
# Wingvox's code path imports (see the note in requirements.txt). This used
# to be a plain install followed by `pip uninstall torch numba scipy ...`,
# which downloaded and unpacked all of it before throwing it away. The real
# dependencies are pinned in requirements.txt above, so this only adds
# mlx_whisper itself.
#
# Older installs still have the discarded packages sitting in their venv
# from that earlier approach, so clear them out once on upgrade.
#
# Intel Macs skip this entirely -- they use faster-whisper (installed above
# via requirements.txt's platform_machine marker), not mlx-whisper, which
# has no x86_64 build at all.
if [[ "$MAC_ARCH" == "arm64" ]]; then
    echo "    Installing mlx-whisper (without its unused torch/scipy deps)…"
    "$VENV_PY" -m pip install --no-deps mlx-whisper -q
    "$VENV_PY" -m pip uninstall -y torch numba scipy llvmlite sympy networkx pillow -q 2>/dev/null || true
else
    echo "    Skipping mlx-whisper — using faster-whisper (installed via requirements.txt) on Intel."
fi

# ---------- 7b. Pre-download the Whisper model ----------
# Both backends fetch their weights lazily on first use, so without this the
# download happens on the first launch instead -- after the install has
# already reported success. Wingvox then sits on "Loading speech model…" for
# minutes with no progress shown anywhere, and any dictation attempted
# meanwhile blocks behind it. Reads as a broken install. Pull it here, where
# the wait is expected.
step "Downloading the speech model (one time)"
if [[ "$MAC_ARCH" == "arm64" ]]; then
    MODEL_DL_OK=1
    "$VENV_PY" -c "import stt_mac; from huggingface_hub import snapshot_download; snapshot_download(repo_id=stt_mac.WHISPER_REPO)" || MODEL_DL_OK=0
else
    MODEL_DL_OK=1
    "$VENV_PY" -c "import stt_intel_mac; stt_intel_mac._get_model()" || MODEL_DL_OK=0
fi
if [[ "$MODEL_DL_OK" != "1" ]]; then
    echo "    WARNING: couldn't pre-download the speech model."
    echo "    Not fatal — Wingvox fetches it on first launch instead, but the"
    echo "    first dictation will be slow. Check your connection."
fi

# ---------- 8. Default glossary ----------
step "Setting up dictionary.txt"
if [[ ! -f "$REPO_DIR/dictionary.txt" ]]; then
    cp "$REPO_DIR/dictionary.default.txt" "$REPO_DIR/dictionary.txt"
    echo "    Created dictionary.txt from the generic default — edit it any"
    echo "    time to add your own names/terms."
else
    echo "    dictionary.txt already exists, leaving it as-is."
fi

# ---------- 9. Build the app ----------
step "Building Wingvox.app"
rm -rf "$REPO_DIR/build" "$REPO_DIR/dist" "$REPO_DIR/Wingvox.app"
# py2app narrates every file it copies and signs even under -q, which buries
# the installer's own progress in pages of internal paths. Hold it all back
# and only surface it if the build actually fails, where it's the first
# thing anyone would need.
BUILD_LOG="$(mktemp)"
if ! "$VENV_PY" setup.py py2app -A -q >"$BUILD_LOG" 2>&1; then
    echo "    Build failed — full output follows." >&2
    echo >&2
    cat "$BUILD_LOG" >&2
    rm -f "$BUILD_LOG"
    exit 1
fi
rm -f "$BUILD_LOG"
mv dist/Wingvox.app "$REPO_DIR/Wingvox.app"
rm -rf "$REPO_DIR/build" "$REPO_DIR/dist"
echo "    Built $REPO_DIR/Wingvox.app"

# ---------- 9b. Collect the background model pull ----------
# Everything above this point overlapped the download. Wait for it here, so
# Wingvox starts with the cleanup model already in place rather than warning
# about a missing model for the first few minutes of its life.
if [[ -n "${PULL_PID:-}" ]]; then
    step "Finishing the cleanup model download"
    echo "    Waiting for qwen2.5:3b (already running since the start of the install)…"
    if wait "$PULL_PID"; then
        echo "    OK — cleanup model ready."
    else
        echo "    WARNING: the cleanup model didn't download. Output follows." >&2
        echo >&2
        cat "$PULL_LOG" >&2
        echo >&2
        echo "    Not fatal: dictation still works, it just pastes raw" >&2
        echo "    transcripts without the cleanup pass. To fix it later:" >&2
        echo "      ollama pull qwen2.5:3b" >&2
    fi
    rm -f "$PULL_LOG"
    PULL_PID=""
fi

# ---------- 10. LaunchAgent ----------
step "Installing the background service"
mkdir -p "$HOME/Library/LaunchAgents"
PLIST_DEST="$HOME/Library/LaunchAgents/com.broganwilliams.wingvox.plist"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/com.broganwilliams.wingvox.plist.template" > "$PLIST_DEST"

if launchctl print "gui/$(id -u)/com.broganwilliams.wingvox" &>/dev/null; then
    launchctl bootout "gui/$(id -u)/com.broganwilliams.wingvox" &>/dev/null || true
    sleep 1  # give launchd a moment to fully tear down the old registration
fi
# The freshly-rebuilt binary above can occasionally still be settling on
# disk right as bootstrap runs; retry once after a brief pause rather than
# failing the whole install over a timing race.
if ! launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST" 2>/dev/null; then
    sleep 2
    launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"
fi
echo "    Wingvox will now start automatically every time you log in."

# ---------- Done ----------
step "Install complete"
echo
echo "One more thing — macOS needs your permission for Wingvox to work."
echo "This can't be done from a script; it needs a few clicks in System Settings."
echo
echo "Turn \"Wingvox\" on in both of these:"
echo "  System Settings > Privacy & Security > Microphone"
echo "  System Settings > Privacy & Security > Accessibility"
echo
echo "If it isn't listed, click +, press Cmd+Shift+G, and paste:"
echo "  $REPO_DIR/Wingvox.app"
echo
echo "(Accessibility also covers Input Monitoring, so there's usually"
echo "nothing to do there. If the hotkey does nothing at all, check that"
echo "list too.)"
echo
echo "Opening the setup guide now..."
# Render SETUP.md to HTML first -- opening the .md directly hands a raw
# markdown file to TextEdit, which is a wall of pipes and asterisks at
# exactly the moment the user needs clear instructions.
if "$VENV_PY" "$REPO_DIR/make_setup_html.py" >/dev/null 2>&1; then
    open "$REPO_DIR/setup.html" 2>/dev/null || true
else
    open "$REPO_DIR/SETUP.md" 2>/dev/null || true
fi
