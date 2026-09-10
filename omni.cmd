@echo off
REM ============================================================
REM  OMNI launcher for Windows - run from any Command Prompt
REM  usage:  omni              -> interactive session
REM          omni "goal text"  -> run one task and exit
REM  Requires: Python 3.10+ on PATH ("python" works)
REM ============================================================
setlocal
set "SCRIPT_DIR=%~dp0"
if not defined PYTHONIOENCODING set "PYTHONIOENCODING=utf-8"

where python >nul 2>nul
if %errorlevel%==0 (
  cd /d "%SCRIPT_DIR%"
  python -m omni %*
  exit /b %errorlevel%
)
where py >nul 2>nul
if %errorlevel%==0 (
  cd /d "%SCRIPT_DIR%"
  py -3 -m omni %*
  exit /b %errorlevel%
)
echo.
echo  [OMNI] Python 3 was not found on PATH.
echo  Install it for free:  https://www.python.org/downloads/
echo  IMPORTANT: during install tick the checkbox
echo  "Add python.exe to PATH", then open a NEW command prompt.
echo.
pause
