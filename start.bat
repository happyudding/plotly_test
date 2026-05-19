@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=C:\Users\sknsw\AppData\Local\Programs\Python\Python313\python.exe"
set "PORT=8000"
set "DATASET=current"

call "%ROOT%terminate.bat"

if exist "%ROOT%output\datasets\%DATASET%" (
    echo Cleaning previous dataset folder: %DATASET%
    rmdir /s /q "%ROOT%output\datasets\%DATASET%"
)

echo.
echo === Building dataset '%DATASET%' (INPUT_PATHS in build.py) ===
"%PYTHON%" "%ROOT%build.py" %DATASET%
if errorlevel 1 (
    echo Build failed. Aborting.
    exit /b 1
)

echo.
echo Starting server on port %PORT%...
start "plotly-dashboard" /D "%ROOT%" "%PYTHON%" "wsgi.py"

timeout /t 2 /nobreak >nul

echo Checking server...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/view/%DATASET%' -UseBasicParsing -TimeoutSec 10; Write-Output ('Server OK: HTTP ' + $r.StatusCode) } catch { Write-Output ('Server check failed: ' + $_.Exception.Message) }"

echo Distribution URL: http://127.0.0.1:%PORT%/view/%DATASET%
echo Dash URL: http://127.0.0.1:%PORT%/dash/%DATASET%
start "" "http://127.0.0.1:%PORT%/dash/%DATASET%"

endlocal
