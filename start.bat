@echo off
setlocal
cd /d "%~dp0"
title Agent Courtroom

set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 goto nopython

if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating the Python environment, one time only...
  %PY% -m venv backend\.venv
  if errorlevel 1 goto fail
)

echo Checking backend packages...
"backend\.venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt
if errorlevel 1 goto fail

where npm >nul 2>nul
if errorlevel 1 goto serve
echo Building the frontend...
pushd frontend
if not exist node_modules call npm install --no-audit --no-fund
call npm run build
if errorlevel 1 echo Frontend build failed, using the bundled build instead.
popd

:serve
if not exist "backend\.env" copy "backend\.env.example" "backend\.env" >nul
echo.
echo ============================================================
echo  Agent Courtroom is starting.
echo  Open http://localhost:8000 in your browser.
echo  Press Ctrl+C in this window to stop it.
echo ============================================================
echo.
start "" http://localhost:8000
pushd backend
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
popd
goto end

:nopython
echo.
echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer. Then run this file again.
pause
exit /b 1

:fail
echo.
echo Something went wrong. Read the message above, then run this file again.
pause
exit /b 1

:end
pause
