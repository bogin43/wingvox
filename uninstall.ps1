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
Write-Host "    Stopped."

# ---------- 2. Scheduled tasks ----------
Step "Removing scheduled tasks"
try { schtasks /delete /tn Wingvox /f 2>$null | Out-Null } catch {}
Write-Host "    Removed 'Wingvox' (the dictation app)."
# install.ps1 also registers its own logon task for Ollama, since winget's
# package doesn't persist one. That task is Wingvox's doing, so it goes too
# -- but only the task, not Ollama itself.
try { schtasks /delete /tn Wingvox-Ollama /f 2>$null | Out-Null } catch {}
Write-Host "    Removed 'Wingvox-Ollama' (the auto-start entry, not Ollama itself)."

# ---------- 3. Built app ----------
Step "Removing the built app"
Remove-Item -Recurse -Force (Join-Path $RepoDir "dist") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $RepoDir "build") -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $RepoDir "wingvox_task.xml") -ErrorAction SilentlyContinue
Write-Host "    Removed dist\, build\, and the generated task XML."

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
