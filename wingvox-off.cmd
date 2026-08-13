@echo off
set TASK=Wingvox
REM Turn Wingvox off until you turn it back on (survives a reboot -- the
REM scheduled task is disabled, not just stopped, so it won't come back at
REM your next login the way a plain "end task" would).
REM
REM Use this when Wingvox is competing for the hotkey or mic with something
REM else: a VM, a game, screen-sharing software, another dictation tool.
REM Run wingvox-on.cmd to bring it back.

schtasks /query /tn %TASK% >nul 2>&1
if errorlevel 1 (
    echo Wingvox doesn't appear to be installed -- no scheduled task named "%TASK%".
    echo Run install.ps1 first.
    echo.
    pause
    exit /b 1
)

schtasks /end /tn %TASK% >nul 2>&1
schtasks /change /tn %TASK% /disable >nul 2>&1
REM Backstop: /end targets the task's own instance, so a copy started some
REM other way (e.g. by double-clicking the exe) would otherwise survive.
taskkill /im Wingvox.exe /f >nul 2>&1

echo Wingvox is OFF. It will stay off until you run wingvox-on.cmd.
echo.
pause
