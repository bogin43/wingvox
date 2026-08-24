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

# ---------- 2. Visual C++ Redistributable ----------
# onnxruntime (faster-whisper's VAD filter dependency, see stt_windows.py's
# vad_filter=True) links against msvcp140_1.dll/vcruntime140_1.dll, which
# ship in this redistributable, not in Windows itself. A machine that's
# never had Visual-Studio-built software installed on it won't have these:
# confirmed on a fresh Windows box where onnxruntime failed to import with
# "DLL load failed" even though everything upstream of it -- Python, pip,
# faster-whisper's own install -- succeeded without a single error. That
# failure only surfaces the first time Wingvox actually tries to transcribe
# something, well after this script has already said "install complete", so
# install it here where a failure is visible and attributable.
Step "Checking for the Visual C++ Redistributable"
if (Test-Path "$env:WINDIR\System32\msvcp140_1.dll") {
    Write-Host "    OK -- already installed."
} else {
    Write-Host "    Not found -- installing via winget."
    winget install --id Microsoft.VCRedist.2015+.x64 -e --source winget --accept-package-agreements --accept-source-agreements
    if (-not (Test-Path "$env:WINDIR\System32\msvcp140_1.dll")) {
        Write-Error "Visual C++ Redistributable install didn't produce msvcp140_1.dll. Install it manually from https://aka.ms/vs/17/release/vc_redist.x64.exe and re-run this script."
        exit 1
    }
}

# ---------- 3. Python 3.12 (x64, specifically) ----------
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

# ---------- 4. Ollama ----------
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

# Earlier versions registered a "Wingvox-Ollama" logon task running
# `ollama.exe serve`. ollama.exe is a CONSOLE-subsystem binary, so that put a
# terminal window on screen at every logon -- and closing it, the obvious
# thing to do with a stray terminal, killed Ollama and silently downgraded
# Wingvox to pasting raw uncleaned transcripts. Wingvox now starts Ollama
# itself, windowless and detached (see start_ollama_background in
# platform_compat.py), so remove the old task on upgrade. The /delete
# legitimately "fails" when there's nothing to remove.
try { schtasks /delete /tn "Wingvox-Ollama" /f 2>$null | Out-Null } catch {}

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 | Out-Null
} catch {
    Write-Host "    Starting Ollama..."
    # Only needed so `ollama pull` below has a server to talk to -- this one
    # is transient and hidden. -WindowStyle Hidden with no redirected std
    # handles can silently fail to spawn in a non-interactive session (no
    # window station to attach to), so redirect to files.
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

# ---------- 5. Pull the cleanup model ----------
Step "Pulling the qwen2.5:3b cleanup model (this may take a while on first run)"
ollama pull qwen2.5:3b

# ---------- 6. Python virtual environment ----------
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

# ---------- 6b. Pre-download the Whisper model ----------
# faster-whisper fetches its weights lazily on first use. Left alone, that
# download (~1GB for small.en) happens on the very first launch instead --
# after this script has already said "install complete" -- so Wingvox sits
# on "Loading speech model..." for minutes with no progress shown anywhere,
# which reads as a broken install. Pull it here, where the wait is expected
# and the user can see it happening.
# Take the model name from stt_windows rather than repeating it here: it
# already resolves WINGVOX_WHISPER_MODEL, so this fetches whatever the app
# will actually load. Naming it again would mean changing the default in
# stt_windows.py silently pre-downloads the wrong weights, and the first
# launch downloads all over again -- the exact delay this step exists to
# remove. install.sh reads stt_mac.WHISPER_REPO the same way.
Step "Downloading the speech model (about 0.5GB -- one time)"
& $VenvPy -c @"
import stt_windows
from faster_whisper import WhisperModel
print('    Fetching ' + stt_windows.WHISPER_MODEL + ' ...')
WhisperModel(stt_windows.WHISPER_MODEL, device='auto', compute_type='auto')
print('    Speech model ready.')
"@
if ($LASTEXITCODE -ne 0) {
    Write-Host "    WARNING: couldn't pre-download the speech model."
    Write-Host "    Not fatal -- Wingvox will download it on first launch instead,"
    Write-Host "    but the first dictation will be slow. Check your connection."
}

# ---------- 7. Default glossary ----------
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

# ---------- 8. Build Wingvox.exe ----------
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

# ---------- 9. Background task ----------
Step "Installing the background task"
# Registering a *new* Task Scheduler task via `schtasks /create /xml` fails
# with "Access is denied" on a real (non-elevated) admin-account Windows
# session, which every default single-user Windows install is -- confirmed
# by reproducing it directly, and confirmed that adding an explicit
# <UserId> to the task XML does NOT fix it either. The denial happens on
# schtasks.exe's own XML-import path specifically. Register-ScheduledTask
# (the newer Task Scheduler API, via CIM/WMI rather than schtasks.exe's XML
# importer) registers the identical task with no elevation prompt at all --
# confirmed working on the same machine, same account, same task
# definition. That's the actual fix, not a fallback: use the cmdlet, not
# schtasks/xml. It also throws a real terminating PowerShell exception on
# failure instead of a discarded stderr string, so a failure here can't
# silently read as success the way the old schtasks-based version did.
# A task last (re-)created through an elevated path -- e.g. an older
# Wingvox version's schtasks/xml-plus-UAC-retry install, or anything else
# that happened to touch it while elevated -- can end up needing elevation
# to unregister too, even though creating a brand-new task with this
# script's own Register-ScheduledTask call never does. Confirmed directly:
# Unregister-ScheduledTask on such a task fails with "Access is denied",
# and swallowing that silently (the previous behavior here) meant the
# subsequent Register-ScheduledTask failed too, with a confusing "Cannot
# create a file when that file already exists" -- the real cause (a
# leftover task blocking the new one) was invisible. Retry the removal
# once, elevated, rather than leaving that failure silent.
try {
    Unregister-ScheduledTask -TaskName Wingvox -Confirm:$false -ErrorAction Stop
} catch {
    if (Get-ScheduledTask -TaskName Wingvox -ErrorAction SilentlyContinue) {
        Write-Host "    Removing an old version of the task needs administrator approval -- a Windows prompt is coming."
        Start-Process powershell -ArgumentList @(
            "-NoProfile", "-Command",
            "Unregister-ScheduledTask -TaskName Wingvox -Confirm:`$false"
        ) -Verb RunAs -Wait -WindowStyle Hidden
    }
}
try {
    $userId = "$env:USERDOMAIN\$env:USERNAME"
    $action = New-ScheduledTaskAction -Execute $ExePath -WorkingDirectory $RepoDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -Priority 7 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName Wingvox -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings `
        -Description "Wingvox push-to-talk dictation background service" -ErrorAction Stop | Out-Null
    Start-ScheduledTask -TaskName Wingvox
    Write-Host "    Wingvox will now start automatically every time you log in."
} catch {
    Write-Host "    WARNING: couldn't register the background task ($($_.Exception.Message))."
    Write-Host "    Wingvox is built but won't start automatically at login. Run this"
    Write-Host "    script again, or launch it by hand each time from: $ExePath"
}

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
# Render SETUP.md to HTML first -- opening the .md directly hands a raw
# markdown file to Notepad, which is a wall of pipes and asterisks at
# exactly the moment the user needs clear instructions.
$SetupHtml = Join-Path $RepoDir "setup.html"
& $VenvPy (Join-Path $RepoDir "make_setup_html.py") 2>$null | Out-Null
$guide = if (Test-Path $SetupHtml) { $SetupHtml } else { Join-Path $RepoDir "SETUP.md" }
try { Start-Process $guide } catch {
    Write-Host "    (Couldn't auto-open it -- read it directly at $guide instead.)"
}
