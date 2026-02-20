$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Root "..")
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"

python -m venv (Join-Path $Root ".venv") | Out-Null
& (Join-Path $Root ".venv\Scripts\Activate.ps1")

pip install -r (Join-Path $Backend "requirements.txt")

Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m uvicorn app.main:app --reload --app-dir $Backend"
Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m http.server 5173 --directory $Frontend"

Write-Host "Backend and frontend started."
