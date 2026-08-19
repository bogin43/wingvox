#!/bin/bash
# Turn Wingvox off, without uninstalling it. Stays off across reboots (the
# LaunchAgent registration itself is removed, not just the running process)
# until wingvox-on.sh brings it back. Useful when Wingvox is competing for
# the hotkey or the mic with something else -- a VM, a game, screen-sharing
# software, another dictation tool.
set -uo pipefail   # no -e: "already off" is success here, not an error to abort on

LABEL="gui/$(id -u)/com.broganwilliams.wingvox"

if ! launchctl print "$LABEL" &>/dev/null; then
    echo "Wingvox is already off."
    exit 0
fi

launchctl bootout "$LABEL" &>/dev/null
# bootout returns before launchd finishes tearing the process down.
for _ in $(seq 1 20); do
    launchctl print "$LABEL" &>/dev/null || break
    sleep 0.25
done

if launchctl print "$LABEL" &>/dev/null; then
    echo "Wingvox didn't fully stop -- try again in a moment." >&2
    exit 1
fi
echo "Wingvox is off. Run ./wingvox-on.sh to bring it back."
