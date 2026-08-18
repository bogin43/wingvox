#!/bin/bash
# Take a published Wingvox update.
#
# Wingvox.app is a py2app alias build: the bundle runs flow.py straight out of
# this folder rather than holding a copy of it (see DEFAULT_SCRIPT in
# Wingvox.app/Contents/Resources/__boot__.py). So a code change lands with a
# pull and a restart -- no rebuild, no reinstall, no re-downloading models.
#
# Changes to requirements.txt or the models are the exception: those need the
# full installer, and this script says so rather than leaving a half-updated
# install behind.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

step() { echo; echo "==> $1"; }

step "Checking for changes"
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "You have uncommitted changes in $REPO_DIR:" >&2
    # --untracked-files=no on purpose: a pull won't touch untracked files,
    # and listing them here makes it look like it would.
    git status --short --untracked-files=no >&2
    echo >&2
    echo "Updating would overwrite them. Commit or discard them first." >&2
    exit 1
fi

BEFORE="$(git rev-parse HEAD)"
git fetch --quiet origin
AFTER="$(git rev-parse origin/HEAD 2>/dev/null || git rev-parse origin/main)"

if [[ "$BEFORE" == "$AFTER" ]]; then
    echo "    Already up to date — nothing to do."
    exit 0
fi

step "What's changing"
git --no-pager log --oneline "$BEFORE..$AFTER"

# Anything that alters the Python environment or the models can't be fixed by
# a restart, so check before pulling and route those to the installer.
NEEDS_INSTALL=""
if ! git diff --quiet "$BEFORE" "$AFTER" -- requirements.txt setup.py stt_mac.py; then
    NEEDS_INSTALL="1"
fi

step "Updating"
git pull --ff-only --quiet
echo "    Now at $(git rev-parse --short HEAD)."

if [[ -n "$NEEDS_INSTALL" ]]; then
    step "This update needs the full installer"
    echo "    It touches the Python dependencies or the speech model, which a"
    echo "    restart alone won't pick up. Run:"
    echo
    echo "      $REPO_DIR/install.sh"
    echo
    exit 0
fi

step "Restarting Wingvox"
if launchctl kickstart -k "gui/$(id -u)/com.broganwilliams.wingvox" 2>/dev/null; then
    echo "    Restarted. Give it a few seconds to reload the speech model."
else
    echo "    Wingvox doesn't appear to be installed as a login service."
    echo "    Run $REPO_DIR/install.sh to set it up."
fi
