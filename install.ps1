# Wingvox installer for Windows -- mirrors install.sh's steps. Builds the
# app locally (PyInstaller) rather than shipping a pre-built .exe, since
# there's no code-signing certificate yet and a pre-built binary would trip
# SmartScreen just as hard as a freshly-built one -- building here at least
# keeps the provenance obvious to anyone who wants to check.

$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoDir

function Step($msg) {
    Write-Host ""
    Write-Host "==> $msg"
}

Step "Installing Wingvox from: $RepoDir"
Write-Host "    This location is now permanent -- the background task references"
Write-Host "    this exact folder path. Don't move it after install without"
Write-Host "    re-running this script."

# ---------- 1. winget ----------
Step "Checking for winget"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Error "winget not found. Install 'App Installer' from the Microsoft Store, or see https://aka.ms/getwinget, then re-run this script."
    exit 1
}
Write-Host "    OK -- winget available."

# ---------- 2. Python 3.12 (x64, specifically) ----------
Step "Checking for Python 3.12 (x64)"
# faster-whisper's ctranslate2 dependency doesn't publish Windows ARM64
# wheels -- only win_amd64. On an ARM64 Windows machine (Surface Pro X/
# Laptop, etc.), an ARM64-native Python would make `pip install -r
# requirements.txt` fail deep into venv setup, well past the point a user
# could self-diagnose it. x64 Python runs fine under Windows-on-ARM's
# built-in x64 emulation, so target x64 explicitly on every machine --
# ARM64 host or not -- via the py launcher's "-64" architecture tag rather
# than letting winget/py pick whatever matches the host.
$pythonOk = $false
try {
    $v = & py -3.12-64 -c "print('ok')" 2>$null
    if ($v -eq "ok") { $pythonOk = $true }
} catch {}
if (-not $pythonOk) {
    Write-Host "    Not found -- installing Python 3.12 (x64) via winget."
    winget install --id Python.Python.3.12 -e --architecture x64 --source winget --accept-package-agreements --accept-source-agreements
    # winget updates the registry's PATH but this running session's $env:Path
    # was captured at shell start, so the py launcher won't resolve without
    # pulling the fresh value back in.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $pythonOk = $false
    try {
        $v = & py -3.12-64 -c "print('ok')" 2>$null
        if ($v -eq "ok") { $pythonOk = $true }
    } catch {}
} else {
    Write-Host "    OK -- already installed."
}
if (-not $pythonOk) {
    Write-Error "Python 3.12 (x64) still isn't available as 'py -3.12-64' after installing. Install it manually from https://www.python.org/downloads/windows/ (pick the x64 installer, even on an ARM64 PC) and re-run this script."
    exit 1
}
$PythonBin = "py"
$PythonArgs = @("-3.12-64")

# ---------- 3. Ollama ----------
Step "Checking for Ollama"
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "    Not found -- installing via winget."
    winget install --id Ollama.Ollama -e --source winget --accept-package-agreements --accept-source-agreements
    # winget installs to a per-user path not yet on PATH in this session.
    $env:Path = "$env:LOCALAPPDATA\Programs\Ollama;$env:Path"
}
# Resolve the full exe path rather than relying on bare "ollama" -- PATH
# resolution has proven unreliable right after a fresh winget install in
# the same session.
$ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollamaExe) { $ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }

# Unlike the Mac install (`brew services start ollama`, a genuinely
# persistent launchd service), winget's Ollama package registers no
# auto-start of its own -- a one-off `ollama serve` here would die with
# this session and never come back after a reboot, leaving Wingvox (which
# does auto-start via its own Task Scheduler entry below) permanently stuck
# on "Ollama not running" until the user manually restarts it. Give it the
# same logon-triggered persistence Wingvox itself gets, further down.
schtasks /create /tn "Wingvox-Ollama" /tr "`"$ollamaExe`" serve" /sc onlogon /rl limited /f | Out-Null

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 | Out-Null
} catch {
    Write-Host "    Starting Ollama..."
    # -WindowStyle Hidden with no redirected std handles can silently fail to
    # spawn in a non-interactive session (no window station to attach to) --
    # redirecting to files sidesteps that.
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\wingvox_ollama_stdout.log" -RedirectStandardError "$env:TEMP\wingvox_ollama_stderr.log"
}
Write-Host -NoNewline "    Waiting for Ollama to come up"
$ollamaReady = $false
for ($i = 1; $i -le 20; $i++) {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 | Out-Null
        Write-Host " -- ready."
        $ollamaReady = $true
        break
    } catch {
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 1
    }
}
if (-not $ollamaReady) {
    Write-Error "Ollama didn't come up after 20s. Launch the Ollama app manually and re-run this script."
    exit 1
}

# ---------- 4. Pull the cleanup model ----------
Step "Pulling the qwen2.5:3b cleanup model (this may take a while on first run)"
ollama pull qwen2.5:3b

# ---------- 5. Python virtual environment ----------
Step "Setting up the Python environment"
$VenvDir = Join-Path $RepoDir "venv"
if (-not (Test-Path $VenvDir)) {
    & $PythonBin @PythonArgs -m venv $VenvDir
    Write-Host "    Created venv."
} else {
    Write-Host "    venv already exists, reusing it."
}
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"

Step "Installing Python dependencies"
& $VenvPy -m pip install --upgrade pip -q
& $VenvPy -m pip install -r requirements.txt -q

# ---------- 5b. Pre-download the Whisper model ----------
# faster-whisper fetches its weights lazily on first use. Left alone, that
# download (~1GB for small.en) happens on the very first launch instead --
# after this script has already said "install complete" -- so Wingvox sits
# on "Loading speech model..." for minutes with no progress shown anywhere,
# which reads as a broken install. Pull it here, where the wait is expected
# and the user can see it happening.
Step "Downloading the speech model (about 1GB -- one time)"
$env:WINGVOX_WHISPER_MODEL = $null
& $VenvPy -c @"
import os, sys
from faster_whisper import WhisperModel
model = os.environ.get('WINGVOX_WHISPER_MODEL') or 'small.en'
print('    Fetching ' + model + ' ...')
WhisperModel(model, device='auto', compute_type='auto')
print('    Speech model ready.')
"@
if ($LASTEXITCODE -ne 0) {
    Write-Host "    WARNING: couldn't pre-download the speech model."
    Write-Host "    Not fatal -- Wingvox will download it on first launch instead,"
    Write-Host "    but the first dictation will be slow. Check your connection."
}

# ---------- 6. Default glossary ----------
Step "Setting up dictionary.txt"
$DataDir = Join-Path $env:LOCALAPPDATA "Wingvox"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$DictPath = Join-Path $DataDir "dictionary.txt"
if (-not (Test-Path $DictPath)) {
    Copy-Item (Join-Path $RepoDir "dictionary.default.txt") $DictPath
    Write-Host "    Created dictionary.txt from the generic default -- edit it any"
    Write-Host "    time to add your own names/terms ($DictPath)."
} else {
    Write-Host "    dictionary.txt already exists, leaving it as-is."
}

# ---------- 7. Build Wingvox.exe ----------
Step "Building Wingvox.exe"
Remove-Item -Recurse -Force (Join-Path $RepoDir "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $RepoDir "dist") -ErrorAction SilentlyContinue
& $VenvPy -m PyInstaller wingvox.spec -y | Out-Null
$ExePath = Join-Path $RepoDir "dist\Wingvox\Wingvox.exe"
if (-not (Test-Path $ExePath)) {
    Write-Error "Build finished but $ExePath wasn't produced -- check the PyInstaller output above."
    exit 1
}
Write-Host "    Built $ExePath"

# ---------- 8. Background task ----------
Step "Installing the background task"
$TaskXmlTemplate = Join-Path $RepoDir "wingvox_task.xml.template"
$TaskXmlPath = Join-Path $RepoDir "wingvox_task.xml"
$TaskXmlContent = (Get-Content $TaskXmlTemplate -Raw) `
    -replace "__EXE_PATH__", $ExePath `
    -replace "__REPO_DIR__", $RepoDir
# schtasks' XML importer wants UTF-16 specifically -- both UTF-8 with a BOM
# ("incorrect document syntax") and UTF-8 without one ("unable to switch the
# encoding") were rejected. Match the template's declared encoding exactly.
[System.IO.File]::WriteAllText($TaskXmlPath, $TaskXmlContent, [System.Text.Encoding]::Unicode)

# /delete legitimately "fails" (no existing task) on a first-ever install --
# $ErrorActionPreference = "Stop" turns that expected stderr output into a
# terminating error unless it's caught explicitly.
try { schtasks /delete /tn Wingvox /f 2>$null | Out-Null } catch {}
schtasks /create /tn Wingvox /xml $TaskXmlPath /f | Out-Null
schtasks /run /tn Wingvox | Out-Null
Write-Host "    Wingvox will now start automatically every time you log in."

# ---------- Done ----------
Step "Install complete"
Write-Host ""
Write-Host "One more thing -- Windows needs your permission for Wingvox to work,"
Write-Host "and the very first launch will likely show a SmartScreen warning"
Write-Host "because this build isn't code-signed yet:"
Write-Host "  'Windows protected your PC' -> click 'More info' -> 'Run anyway'."
Write-Host ""
Write-Host "If dictation ever says 'Heard nothing' even when speaking clearly,"
Write-Host "check Settings > Privacy & security > Microphone and make sure"
Write-Host "  $ExePath"
Write-Host "(or 'Wingvox') is allowed."
Write-Host ""
Write-Host "Opening the setup guide now..."
try { Start-Process (Join-Path $RepoDir "SETUP.md") } catch {
    Write-Host "    (Couldn't auto-open it -- read it directly at $(Join-Path $RepoDir 'SETUP.md') instead.)"
}
