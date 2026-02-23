# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

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

function Get-ServicePid {
  param([string]$Name)
  $output = sc.exe queryex $Name 2>$null
  if (-not $output) {
    return $null
  }
  foreach ($line in $output) {
    if ($line -match "PID\s*:\s*(\d+)") {
      return [int]$Matches[1]
    }
  }
  return $null
}

function Stop-ServiceTree {
  param([string]$Name)
  sc.exe stop $Name | Out-Null
  Start-Sleep -Seconds 2
  $pid = Get-ServicePid -Name $Name
  if ($pid -and $pid -gt 0) {
    taskkill.exe /PID $pid /T /F | Out-Null
  }
}

Write-Host "Creating/updating service $ServiceName ..."

Stop-ServiceTree -Name $ServiceName
sc.exe delete $ServiceName | Out-Null

sc.exe create $ServiceName binPath= $binPath start= auto DisplayName= $displayName
sc.exe description $ServiceName "4ham backend API and websocket service"

Write-Host "Setting required environment variables in machine scope..."
[Environment]::SetEnvironmentVariable("FT_EXTERNAL_ENABLE", "1", "Machine")
[Environment]::SetEnvironmentVariable("FT_EXTERNAL_MODES", "FT8,FT4", "Machine")
[Environment]::SetEnvironmentVariable("DIREWOLF_KISS_ENABLE", "1", "Machine")
[Environment]::SetEnvironmentVariable("DIREWOLF_AUTOSTART", "1", "Machine")
[Environment]::SetEnvironmentVariable("DIREWOLF_CMD", "direwolf -t 0 -p", "Machine")

Write-Host "Starting service..."
sc.exe start $ServiceName

Write-Host "Done. Use 'sc.exe query $ServiceName' to check status."
