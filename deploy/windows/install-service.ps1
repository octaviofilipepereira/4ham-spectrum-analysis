# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

param(
  [string]$ProjectDir = "C:\\4ham-spectrum-analysis",
  [string]$ServiceName = "4ham-spectrum-analysis",
  [string]$PythonExe = ""
)

if (-not $PythonExe) {
  $PythonExe = Join-Path $ProjectDir ".venv\\Scripts\\python.exe"
}

$displayName = "4ham Spectrum Analysis Backend"
$binPath = "`"$PythonExe`" -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000"

Write-Host "Creating/updating service $ServiceName ..."

sc.exe stop $ServiceName | Out-Null
sc.exe delete $ServiceName | Out-Null

sc.exe create $ServiceName binPath= $binPath start= auto DisplayName= $displayName
sc.exe description $ServiceName "4ham backend API and websocket service"

Write-Host "Setting required environment variables in machine scope..."
[Environment]::SetEnvironmentVariable("WSJTX_UDP_ENABLE", "1", "Machine")
[Environment]::SetEnvironmentVariable("WSJTX_AUTOSTART", "0", "Machine")
[Environment]::SetEnvironmentVariable("DIREWOLF_KISS_ENABLE", "1", "Machine")
[Environment]::SetEnvironmentVariable("DIREWOLF_AUTOSTART", "1", "Machine")
[Environment]::SetEnvironmentVariable("DIREWOLF_CMD", "direwolf -t 0 -p", "Machine")

Write-Host "Starting service..."
sc.exe start $ServiceName

Write-Host "Done. Use 'sc.exe query $ServiceName' to check status."
