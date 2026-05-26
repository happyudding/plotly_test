@echo off
setlocal

set "ROOT=%~dp0"
if not defined PORT set "PORT=8000"
if not defined HOST set "HOST=127.0.0.1"
if not defined DATASET set "DATASET=current"

rem Resolve Python interpreter.
rem   PY_CMD is the already-quoted interpreter (plus optional launcher args).
rem   Examples: "C:\Python313\python.exe"   or   py -3
set "PY_CMD="

if defined PYTHON (
    set PY_CMD="%PYTHON%"
    goto :py_ok
)
if exist "%ROOT%.venv\Scripts\python.exe" (
    set PY_CMD="%ROOT%.venv\Scripts\python.exe"
    goto :py_ok
)
if exist "%ROOT%venv\Scripts\python.exe" (
    set PY_CMD="%ROOT%venv\Scripts\python.exe"
    goto :py_ok
)
for /f "delims=" %%P in ('where python.exe 2^>nul') do (
    set PY_CMD="%%P"
    goto :py_ok
)
where py.exe >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto :py_ok
)
echo [start] ERROR: Python interpreter not found.
echo [start] Set PYTHON env var, create .venv, or add python to PATH.
exit /b 1

:py_ok
echo [start] Python: %PY_CMD%
echo [start] Host:   %HOST%
echo [start] Port:   %PORT%

call "%ROOT%terminate.bat"

echo.
echo [start] Starting server on %HOST%:%PORT% ...
rem PY_CMD already contains quotes when it is a path; first quoted arg to start is the window title.
start "plotly-dashboard" /D "%ROOT%" %PY_CMD% -u wsgi.py

echo [start] Waiting for server to listen (up to 60s) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port = [int]'%PORT%'; for ($i = 0; $i -lt 120; $i++) { if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { Write-Host '[start] Server is listening.'; exit 0 } ; Start-Sleep -Milliseconds 500 } ; Write-Host '[start] Timeout waiting for server.'; exit 1"
if errorlevel 1 (
    echo [start] Check the server window for errors.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://%HOST%:%PORT%/pe/report/' -UseBasicParsing -TimeoutSec 15; Write-Output ('[start] HTTP ' + $r.StatusCode) } catch { Write-Output ('[start] HTTP check failed: ' + $_.Exception.Message) }"

echo [start] URL: http://%HOST%:%PORT%/pe/report/
start "" "http://%HOST%:%PORT%/pe/report/"

endlocal
