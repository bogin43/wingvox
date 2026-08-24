#!/bin/bash
# Change the dictation hotkey, without needing to know the venv path or the
# launchctl restart command by heart. Wraps `flow.py set-hotkey` (which taps
# the interactive picker, then only writes the setting) and the restart it
# requires into one command, so this is the thing to hand a member who asks
# to switch keys rather than the two raw commands underneath it.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$REPO_DIR/venv/bin/python"
LABEL="com.broganwilliams.wingvox"

if [[ ! -x "$VENV_PY" ]]; then
    echo "No venv at $REPO_DIR/venv -- run install.sh first." >&2
    exit 1
fi

# flow.py set-hotkey shows the tap-to-pick+confirm UI, then only writes
# hotkey.txt and prints the restart command rather than running it --
# keeping the file-write and the restart as separate concerns there. This
# script exists specifically to fold both into one step, so run it here
# instead of asking the user to copy the command flow.py prints.
"$VENV_PY" "$REPO_DIR/flow.py" set-hotkey

echo
echo "Restarting Wingvox…"
if launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null; then
    echo "Done. Give it a few seconds to reload, then try the new key."
else
    echo "Wingvox doesn't appear to be installed as a login service." >&2
    echo "Run $REPO_DIR/install.sh to set it up." >&2
    exit 1
fi
