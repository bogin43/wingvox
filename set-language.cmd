@echo off
setlocal
REM Change the dictation language, without needing to know the venv path or
REM the schtasks restart commands by heart. Wraps `flow.py set-language`
REM (which only writes the setting) and the restart it requires into one
REM command -- the Windows counterpart of set-language.sh, which looks for
REM venv\bin\python (the Mac layout) and can't run here at all.
set TASK=Wingvox
set REPO_DIR=%~dp0
set VENV_PY=%REPO_DIR%venv\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo No venv at %REPO_DIR%venv -- run install.ps1 first.
    exit /b 1
)

set CODE=%~1
if "%CODE%"=="" (
    echo Usage: set-language.cmd ^<code^>   e.g. fr ^(French^), nl ^(Dutch/Flemish^), en ^(English^)
    echo.
    "%VENV_PY%" "%REPO_DIR%flow.py" set-language ""
    exit /b 0
)

"%VENV_PY%" "%REPO_DIR%flow.py" set-language %CODE%

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
echo Done. Give it a few seconds to reload, then try dictating.
