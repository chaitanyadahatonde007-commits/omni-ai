@echo off
REM ============================================================
REM  OMNI one-click setup for Windows
REM  - installs Python requirements (free)
REM  - creates the `omni` command on your PATH
REM  Run from the omni-ai folder:   install.bat
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo  ==============================================
echo    OMNI setup - everything free
echo  ==============================================
echo.

where python >nul 2>nul
if %errorlevel%==0 ( set "PY=python" ) else (
  where py >nul 2>nul
  if !errorlevel!==0 ( set "PY=py -3" ) else (
    echo  [X] Python 3 not found. Install it free from
    echo      https://www.python.org/downloads/  and tick
    echo      "Add python.exe to PATH", then rerun this file.
    pause
    exit /b 1
  )
)

echo  [1/3] Installing libraries (rich, requests, beautifulsoup4,
echo         trafilatura)... 
%PY% -m pip install --upgrade pip >nul 2>nul
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo  [X] pip install failed - check your internet and retry.
  pause
  exit /b 1
)

echo  [2/3] Creating 'omni' command on your PATH...
set "LINKDIR=%USERPROFILE%\.omni-bin"
if not exist "%LINKDIR%" mkdir "%LINKDIR%"
copy /Y "%~dp0omni.cmd" "%LINKDIR%\omni.cmd" >nul
for /f "skip=2 tokens=1,2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "OLDPATH=%%C"
echo !OLDPATH! | findstr /i /c:"omni-bin" >nul
if errorlevel 1 (
  setx PATH "!OLDPATH!;%LINKDIR%" >nul
)

echo  [3/3] First-run test...
"%LINKDIR%\omni.cmd" --version
if errorlevel 1 (
  echo  [X] launch failed - see errors above.
  pause
  exit /b 1
)

echo.
echo  ==============================================
echo    DONE! Open a NEW Command Prompt and type:
echo        omni
echo    It will ask for ONE free AI key (choose the
echo    Gemini option) - get one at:
echo        https://aistudio.google.com/apikey
echo  ==============================================
pause
