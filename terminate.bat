@echo off
setlocal

set "PORT=8000"

echo Stopping server on port %PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pids = @(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); " ^
  "if ($pids.Count -eq 0) { Write-Host 'No LISTENING process found on port %PORT%.'; exit 0 }; " ^
  "foreach ($procId in $pids) { Write-Host ('Terminating PID ' + $procId); Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }; " ^
  "Write-Host 'Server stopped.'"

endlocal
