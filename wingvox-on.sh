#!/bin/bash
# Turn Wingvox back on after wingvox-off.sh.
set -uo pipefail   # no -e: "already on" is success here, not an error to abort on

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL_ID="com.broganwilliams.wingvox"
LABEL="gui/$(id -u)/$LABEL_ID"
PLIST="$HOME/Library/LaunchAgents/$LABEL_ID.plist"

if launchctl print "$LABEL" &>/dev/null; then
    echo "Wingvox is already on."
    exit 0
fi

if [[ ! -f "$PLIST" ]]; then
    echo "No LaunchAgent found at $PLIST -- run install.sh first." >&2
    exit 1
fi

# The freshly-restarted binary can occasionally still be settling on disk
# right as bootstrap runs -- retry once after a brief pause rather than
# failing over a timing race (same pattern install.sh itself uses).
if ! launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null; then
    sleep 2
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
fi
echo "Wingvox is on."
