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
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 2 | Out-Null
} catch {
    Write-Host "    Starting Ollama..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
}
Write-Host -NoNewline "    Waiting for Ollama to come up"
$ollamaReady = $false
for ($i = 1; $i -le 20; $i++) {
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 2 | Out-Null
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
(Get-Content $TaskXmlTemplate -Raw) `
    -replace "__EXE_PATH__", $ExePath `
    -replace "__REPO_DIR__", $RepoDir `
    | Out-File -FilePath $TaskXmlPath -Encoding Unicode

schtasks /delete /tn Wingvox /f 2>$null | Out-Null
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
Start-Process (Join-Path $RepoDir "SETUP.md")
