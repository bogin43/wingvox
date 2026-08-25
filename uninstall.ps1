# Wingvox uninstaller for Windows -- reverses install.ps1.
#
# Removes what Wingvox itself created. Deliberately does NOT remove Python,
# Ollama, or the downloaded models: they're shared tools a user may well have
# installed for other reasons, and silently deleting several GB of someone
# else's stuff is not an uninstaller's job. Those are printed as optional
# manual steps at the end instead.

$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $env:LOCALAPPDATA "Wingvox"

function Step($msg) {
    Write-Host ""
    Write-Host "==> $msg"
}

function Remove-Stubbornly($path) {
    # Windows releases a killed process's file handles asynchronously, so a
    # delete issued immediately after taskkill can fail on the very exe that
    # was just running. Silently swallowing that (and still printing
    # "Removed") left the built app on disk while claiming otherwise -- so
    # retry for a few seconds, then report what actually happened.
    if (-not (Test-Path $path)) { return $true }
    for ($i = 0; $i -lt 10; $i++) {
        try {
            Remove-Item -Recurse -Force $path -ErrorAction Stop
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return -not (Test-Path $path)
}

Write-Host "This will remove Wingvox's background tasks and its built app."
Write-Host "Your Python install, Ollama, and the downloaded AI models are left alone."
Write-Host ""
$confirm = Read-Host "Continue? (y/N)"
if ($confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "Cancelled -- nothing was changed."
    exit 0
}

# ---------- 1. Stop it ----------
Step "Stopping Wingvox"
# Each of these legitimately "fails" when the thing isn't there (never
# installed, already removed, not currently running). Under
# $ErrorActionPreference = "Stop" an expected failure would abort the whole
# uninstall partway through, so swallow them individually.
try { schtasks /end /tn Wingvox 2>$null | Out-Null } catch {}
try { taskkill /im Wingvox.exe /f 2>$null | Out-Null } catch {}
# Wait for it to actually be gone, not just signalled -- the file deletions
# below race the OS releasing its handles otherwise.
for ($i = 0; $i -lt 20; $i++) {
    if (-not (Get-Process Wingvox -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 250
}
Write-Host "    Stopped."

# ---------- 2. Scheduled tasks ----------
Step "Removing scheduled tasks"
try { schtasks /delete /tn Wingvox /f 2>$null | Out-Null } catch {}
Write-Host "    Removed 'Wingvox' (the dictation app)."
try { schtasks /delete /tn Wingvox-Updater /f 2>$null | Out-Null } catch {}
Write-Host "    Removed 'Wingvox-Updater' (the click-to-update helper task)."
# Earlier versions registered a separate logon task to run `ollama serve`,
# since winget's package doesn't persist one. install.ps1 no longer creates
# this task (Wingvox starts Ollama itself, see start_ollama_background in
# platform_compat.py) -- this is upgrade cleanup for machines that still
# have the old task from before that change, not something a fresh install
# ever creates. The /delete legitimately "fails" when there's nothing to
# remove.
try { schtasks /delete /tn Wingvox-Ollama /f 2>$null | Out-Null } catch {}
Write-Host "    Removed 'Wingvox-Ollama' if present (an old auto-start entry, not Ollama itself)."

# ---------- 3. Built app ----------
Step "Removing the built app"
$leftovers = @()
foreach ($item in @("dist", "build")) {
    $path = Join-Path $RepoDir $item
    if (-not (Remove-Stubbornly $path)) { $leftovers += $path }
}
if ($leftovers.Count -eq 0) {
    Write-Host "    Removed dist\ and build\."
} else {
    Write-Host "    Removed what it could, but these are still in use:"
    $leftovers | ForEach-Object { Write-Host "      $_" }
    Write-Host "    Something still has them open. Reboot and delete them by hand."
}

# ---------- 4. User data (opt-in) ----------
Step "Personal settings"
if (Test-Path $DataDir) {
    Write-Host "    Your glossary and corrections live in:"
    Write-Host "      $DataDir"
    Write-Host "    (dictionary.txt, corrections.txt, and the log)"
    $delData = Read-Host "    Delete these too? (y/N)"
    if ($delData -eq "y" -or $delData -eq "Y") {
        Remove-Item -Recurse -Force $DataDir -ErrorAction SilentlyContinue
        Write-Host "    Deleted."
    } else {
        Write-Host "    Kept -- reinstalling later will pick them back up."
    }
} else {
    Write-Host "    None found, nothing to remove."
}

# ---------- Done ----------
Step "Wingvox uninstalled"
Write-Host ""
Write-Host "Optional cleanup, only if you don't want them for anything else:"
Write-Host ""
Write-Host "  The Python environment (about 270MB):"
Write-Host "    Remove-Item -Recurse -Force `"$RepoDir\venv`""
Write-Host ""
Write-Host "  The speech model (about 1GB):"
Write-Host "    Remove-Item -Recurse -Force `"$env:USERPROFILE\.cache\huggingface`""
Write-Host ""
Write-Host "  The cleanup model (about 2GB):"
Write-Host "    ollama rm qwen2.5:3b"
Write-Host ""
Write-Host "  Ollama and Python themselves:"
Write-Host "    winget uninstall Ollama.Ollama"
Write-Host "    winget uninstall Python.Python.3.12"
Write-Host ""
Write-Host "  And finally this folder:"
Write-Host "    $RepoDir"
Write-Host ""
