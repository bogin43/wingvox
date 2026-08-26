# Take a published Wingvox update on Windows.
#
# Unlike Mac's Wingvox.app (a py2app alias build that runs flow.py straight
# out of the checkout, so a pull + restart is enough), Windows runs a
# compiled PyInstaller exe in dist\Wingvox\. Pulling new source leaves that
# exe untouched -- a restart alone would keep running the OLD code while
# reporting itself up to date. So every Windows update needs a rebuild, not
# just a restart; there's no cheaper path to distinguish, unlike Mac's
# update.sh which only reaches for the full installer when
# requirements.txt/setup.py/stt_mac.py changed.
#
# install.ps1 already does everything a rebuild needs (Python/Ollama checks,
# pip install, PyInstaller build, task registration+restart) and is
# idempotent -- steps that are already satisfied are skipped quickly rather
# than redone. So this script's job is just: check for a clean tree, pull,
# then hand off to install.ps1 rather than duplicating its logic.

$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoDir

function Step($msg) {
    Write-Host ""
    Write-Host "==> $msg"
}

Step "Checking for changes"
$dirty = git status --short --untracked-files=no
if ($dirty) {
    Write-Host "You have uncommitted changes in $RepoDir`:" -ForegroundColor Red
    $dirty | ForEach-Object { Write-Host $_ }
    Write-Host ""
    Write-Host "Updating would overwrite them. Commit or discard them first." -ForegroundColor Red
    exit 1
}

$Before = git rev-parse HEAD
git fetch --quiet origin
$After = git rev-parse origin/main

if ($Before -eq $After) {
    Write-Host "    Already up to date -- nothing to do."
    exit 0
}

Step "What's changing"
git --no-pager log --oneline "$Before..$After"

Step "Pulling"
git pull --ff-only --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pull failed -- your local branch may have diverged from origin, or the network dropped mid-pull. Run 'git status' in $RepoDir to see what's going on."
    exit 1
}
Write-Host "    Now at $(git rev-parse --short HEAD)."

Step "Rebuilding and restarting (this is install.ps1 -- it skips whatever's already up to date)"
# Tells install.ps1 this is a background update rather than someone sitting
# at a fresh install, so it doesn't pop the setup guide open unannounced --
# see install.ps1's own WINGVOX_UPDATE check at the end.
$env:WINGVOX_UPDATE = "1"
& (Join-Path $RepoDir "install.ps1")
