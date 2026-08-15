#!/bin/bash
# Wingvox uninstaller for macOS -- reverses install.sh.
#
# Removes what Wingvox itself created. Deliberately does NOT remove Homebrew,
# Python, Ollama, or the downloaded models: they're shared tools a user may
# well have installed for other reasons, and silently deleting several GB of
# someone else's stuff is not an uninstaller's job. Those are printed as
# optional manual steps at the end instead.
set -uo pipefail   # no -e: nearly every step here legitimately "fails" when
                   # the thing it removes was never installed

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_DEST="$HOME/Library/LaunchAgents/com.broganwilliams.wingvox.plist"
LABEL="gui/$(id -u)/com.broganwilliams.wingvox"

step() { echo; echo "==> $1"; }

echo "This will stop Wingvox, remove its login service, and delete the app"
echo "it built. Homebrew, Python, Ollama and the downloaded AI models are"
echo "left alone."
echo
read -r -p "Continue? (y/N) " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Cancelled — nothing was changed."
    exit 0
fi

# ---------- 1. Stop the background service ----------
step "Stopping Wingvox"
launchctl bootout "$LABEL" &>/dev/null
# bootout returns before launchd has finished tearing the process down, and
# the deletions below race that. Wait for it to actually be gone.
for _ in $(seq 1 20); do
    launchctl print "$LABEL" &>/dev/null || break
    sleep 0.25
done
# A copy started by hand (./Wingvox.app/Contents/MacOS/Wingvox) isn't under
# launchd's control and survives the bootout.
pkill -f "Wingvox.app/Contents/MacOS/Wingvox" &>/dev/null
echo "    Stopped."

# ---------- 2. LaunchAgent ----------
step "Removing the login service"
if [[ -f "$PLIST_DEST" ]]; then
    rm -f "$PLIST_DEST"
    echo "    Removed $PLIST_DEST"
    echo "    Wingvox will no longer start when you log in."
else
    echo "    None installed, nothing to remove."
fi

# ---------- 3. Built app ----------
step "Removing the built app"
removed=()
for item in Wingvox.app build dist setup.html; do
    if [[ -e "$REPO_DIR/$item" ]]; then
        rm -rf "${REPO_DIR:?}/$item" && removed+=("$item")
    fi
done
if [[ ${#removed[@]} -gt 0 ]]; then
    echo "    Removed: ${removed[*]}"
else
    echo "    Nothing built here, nothing to remove."
fi
rm -f "$REPO_DIR/wingvox.lock"

# ---------- 4. Personal settings (opt-in) ----------
# On the Mac these live in the repo folder itself (platform_compat.data_dir),
# not in Application Support, so they'd otherwise survive as loose files.
step "Personal settings"
personal=()
for f in dictionary.txt corrections.txt wingvox.log wingvox.log.old; do
    [[ -f "$REPO_DIR/$f" ]] && personal+=("$f")
done
if [[ ${#personal[@]} -gt 0 ]]; then
    echo "    Your glossary, corrections and log are in:"
    echo "      $REPO_DIR"
    echo "    (${personal[*]})"
    read -r -p "    Delete these too? (y/N) " del_data
    if [[ "$del_data" == "y" || "$del_data" == "Y" ]]; then
        for f in "${personal[@]}"; do rm -f "${REPO_DIR:?}/$f"; done
        echo "    Deleted."
    else
        echo "    Kept — reinstalling later will pick them back up."
    fi
else
    echo "    None found, nothing to remove."
fi

# ---------- Done ----------
step "Wingvox uninstalled"
echo
echo "macOS keeps its own record of the permissions you granted. Wingvox is"
echo "gone, so they do nothing now, but to clear the entries by hand:"
echo "  System Settings > Privacy & Security > Microphone"
echo "  System Settings > Privacy & Security > Accessibility"
echo "Select Wingvox in each list and click the minus button."
echo
echo "Optional cleanup, only if you don't want them for anything else:"
echo
echo "  The Python environment (about 300MB):"
echo "    rm -rf \"$REPO_DIR/venv\""
echo
echo "  The speech model (about 450MB):"
echo "    rm -rf ~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo-q4"
echo
echo "  The cleanup model (about 1.8GB):"
echo "    ollama rm qwen2.5:3b"
echo
echo "  Ollama itself, including its login service:"
echo "    brew services stop ollama && brew uninstall ollama"
echo
echo "  And finally this folder:"
echo "    rm -rf \"$REPO_DIR\""
echo
