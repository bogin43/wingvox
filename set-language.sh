#!/bin/bash
# Change the dictation language, without needing to know the venv path or
# the launchctl restart command by heart. Wraps `flow.py set-language`
# (which only writes the setting) and the restart it requires into one
# command -- the thing to hand a non-English-speaking member rather than
# the raw commands underneath it.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$REPO_DIR/venv/bin/python"
LABEL="com.broganwilliams.wingvox"

if [[ ! -x "$VENV_PY" ]]; then
    echo "No venv at $REPO_DIR/venv -- run install.sh first." >&2
    exit 1
fi

CODE="${1:-}"
if [[ -z "$CODE" ]]; then
    echo "Usage: ./set-language.sh <code>   e.g. fr (French), nl (Dutch/Flemish), en (English)"
    echo
    "$VENV_PY" "$REPO_DIR/flow.py" set-language ""
    exit 0
fi

"$VENV_PY" "$REPO_DIR/flow.py" set-language "$CODE"

echo
echo "Restarting Wingvox…"
if launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null; then
    echo "Done. Give it a few seconds to reload, then try dictating."
else
    echo "Wingvox doesn't appear to be installed as a login service." >&2
    echo "Run $REPO_DIR/install.sh to set it up." >&2
    exit 1
fi
