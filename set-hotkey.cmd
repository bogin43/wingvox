@echo off
setlocal
REM Change the dictation hotkey, without needing to know the venv path or
REM the schtasks restart commands by heart. Wraps `flow.py set-hotkey`
REM (which shows the tap-to-pick+confirm UI, then only writes the setting)
REM and the restart it requires into one command -- the Windows counterpart
REM of set-hotkey.sh.
set TASK=Wingvox
set REPO_DIR=%~dp0
set VENV_PY=%REPO_DIR%venv\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo No venv at %REPO_DIR%venv -- run install.ps1 first.
    exit /b 1
)

"%VENV_PY%" "%REPO_DIR%flow.py" set-hotkey

echo.
echo Restarting Wingvox...
schtasks /query /tn %TASK% >nul 2>&1
if errorlevel 1 (
    echo Wingvox doesn't appear to be installed as a login task.
    echo Run %REPO_DIR%install.ps1 to set it up.
    exit /b 1
)
schtasks /end /tn %TASK% >nul 2>&1
schtasks /run /tn %TASK% >nul 2>&1
echo Done. Give it a few seconds to reload, then try the new key.
