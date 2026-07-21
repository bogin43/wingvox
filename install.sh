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

step "Installing Wingvox from: $REPO_DIR"
echo "    This location is now permanent — the app and its background"
echo "    service both reference this exact folder path. Don't move it"
echo "    after install without re-running this script."

# ---------- 1. Apple Silicon check ----------
step "Checking for Apple Silicon"
if [[ "$(uname -m)" != "arm64" ]]; then
    echo "Wingvox requires an Apple Silicon Mac (M1/M2/M3/M4)." >&2
    echo "This Mac reports '$(uname -m)', which the ML framework Wingvox" >&2
    echo "is built on (mlx) does not support." >&2
    exit 1
fi
echo "    OK — Apple Silicon detected."

# ---------- 2. Xcode Command Line Tools ----------
step "Checking for Xcode Command Line Tools"
if ! xcode-select -p &>/dev/null; then
    echo "    Not found — triggering the install dialog."
    xcode-select --install
    echo
    echo "Finish the Command Line Tools install in the dialog that just"
    echo "opened, then re-run this script (./install.sh)."
    exit 0
fi
echo "    OK — already installed."

# ---------- 3. Homebrew ----------
step "Checking for Homebrew"
if ! command -v brew &>/dev/null; then
    echo "    Not found — installing Homebrew (you may be prompted for your password)."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
fi
echo "    OK — Homebrew available at $(command -v brew)."

# ---------- 4. python@3.12 ----------
step "Checking for python@3.12"
brew list python@3.12 &>/dev/null || brew install python@3.12
PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
echo "    OK — using $PYTHON_BIN"

# ---------- 5. Ollama ----------
step "Checking for Ollama"
brew list ollama &>/dev/null || brew install ollama
brew services start ollama &>/dev/null || true
echo -n "    Waiting for Ollama to come up"
for i in $(seq 1 20); do
    if curl -s -o /dev/null http://localhost:11434/api/version; then
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

# ---------- 6. Pull the cleanup model ----------
step "Pulling the qwen2.5:3b cleanup model (this may take a while on first run)"
ollama pull qwen2.5:3b

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
echo "    Removing unused transitive dependencies (torch/numba/scipy/llvmlite)…"
"$VENV_PY" -m pip uninstall -y torch numba scipy llvmlite -q 2>/dev/null || true

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
"$VENV_PY" setup.py py2app -A -q
mv dist/Wingvox.app "$REPO_DIR/Wingvox.app"
rm -rf "$REPO_DIR/build" "$REPO_DIR/dist"
echo "    Built $REPO_DIR/Wingvox.app"

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
RESOLVED_PY="$("$VENV_PY" -c 'import sys; print(sys.executable)')"
echo
echo "One more thing — macOS needs your permission for Wingvox to work."
echo "This can't be done from a script; it needs a few clicks in System Settings."
echo
echo "The exact program that needs permission is:"
echo "  $RESOLVED_PY"
echo "(System Settings shows it as a generic \"Python\" entry — if you have"
echo "more than one, match this exact path.)"
echo
echo "Opening the setup guide now..."
open "$REPO_DIR/SETUP.md" 2>/dev/null || true
