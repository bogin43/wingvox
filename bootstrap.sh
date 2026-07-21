#!/bin/bash
# One-line installer entry point (curl | bash). Wingvox has to be built from
# source per-machine (see install.sh for why), so this script's only job is
# to get a full checkout onto disk, then hand off to the real installer.
set -euo pipefail

REPO_URL="https://github.com/bogin43/wingvox.git"
TARGET_DIR="$HOME/wingvox"

if [[ "$(uname -m)" != "arm64" ]]; then
    echo "Wingvox requires an Apple Silicon Mac (M1/M2/M3/M4)." >&2
    echo "This Mac reports '$(uname -m)', which the ML framework Wingvox" >&2
    echo "is built on (mlx) does not support." >&2
    exit 1
fi

if [[ -d "$TARGET_DIR/.git" ]]; then
    echo "==> Wingvox already cloned at $TARGET_DIR — pulling latest"
    git -C "$TARGET_DIR" pull --ff-only
elif [[ -e "$TARGET_DIR" ]]; then
    echo "$TARGET_DIR already exists and isn't a Wingvox checkout." >&2
    echo "Move or remove it, then re-run this command." >&2
    exit 1
else
    echo "==> Cloning Wingvox to $TARGET_DIR"
    git clone "$REPO_URL" "$TARGET_DIR"
fi

exec "$TARGET_DIR/install.sh"
