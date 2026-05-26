@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=C:\Users\sknsw\AppData\Local\Programs\Python\Python313\python.exe"
set "PORT=8000"
set "DATASET=current"

call "%ROOT%terminate.bat"

echo.
echo Starting server on port %PORT%...
start "plotly-dashboard" /D "%ROOT%" "%PYTHON%" -u "wsgi.py"

timeout /t 2 /nobreak >nul

echo Checking server...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/pe/report/' -UseBasicParsing -TimeoutSec 10; Write-Output ('Server OK: HTTP ' + $r.StatusCode) } catch { Write-Output ('Server check failed: ' + $_.Exception.Message) }"

echo Report Analysis URL: http://127.0.0.1:%PORT%/pe/report/
start "" "http://127.0.0.1:%PORT%/pe/report/"

endlocal
