@echo off
setlocal
cd /d "%~dp0"
title Agent Courtroom (development)

set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"

if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating the Python environment, one time only...
  %PY% -m venv backend\.venv
)
"backend\.venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt
if not exist "backend\.env" copy "backend\.env.example" "backend\.env" >nul

if not exist "frontend\node_modules" (
  pushd frontend
  call npm install --no-audit --no-fund
  popd
)

start "Agent Courtroom - backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
start "Agent Courtroom - frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 5 >nul
start "" http://localhost:5173
echo Two windows were opened (backend and frontend). Close them to stop the app.
