@echo off
set TASK=Wingvox
REM Turn Wingvox back on after wingvox-off.cmd, and start it right now
REM rather than waiting for the next login.

schtasks /query /tn %TASK% >nul 2>&1
if errorlevel 1 (
    echo Wingvox doesn't appear to be installed -- no scheduled task named "%TASK%".
    echo Run install.ps1 first.
    echo.
    pause
    exit /b 1
)

schtasks /change /tn %TASK% /enable >nul 2>&1
schtasks /run /tn %TASK% >nul 2>&1

echo Wingvox is ON. Give it a few seconds to load, then hold Right Alt to dictate.
echo.
echo (First launch after a reboot takes longer -- it loads the speech model.)
echo.
pause
