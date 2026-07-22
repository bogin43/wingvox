# One-line installer entry point: irm <url> | iex
# Wingvox has to be built from source per-machine (see install.ps1 for why),
# so this script's only job is to get a full checkout onto disk, then hand
# off to the real installer.

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/bogin43/wingvox.git"
$TargetDir = Join-Path $env:USERPROFILE "wingvox"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git is required but wasn't found. Install it (winget install --id Git.Git -e), then re-run this command."
    exit 1
}

if (Test-Path (Join-Path $TargetDir ".git")) {
    Write-Host "==> Wingvox already cloned at $TargetDir -- pulling latest"
    git -C $TargetDir pull --ff-only
} elseif (Test-Path $TargetDir) {
    Write-Error "$TargetDir already exists and isn't a Wingvox checkout. Move or remove it, then re-run this command."
    exit 1
} else {
    Write-Host "==> Cloning Wingvox to $TargetDir"
    git clone $RepoUrl $TargetDir
}

# Windows' execution policy (Restricted/RemoteSigned by default) only gates
# loading a .ps1 FILE from disk -- it doesn't gate this bootstrap script
# itself when run via `irm ... | iex`. So install.ps1's invocation is the
# only thing that needs the bypass, scoped to just this one process, not a
# system-wide setting change.
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $TargetDir "install.ps1")
