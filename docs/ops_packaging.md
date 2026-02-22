<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 16:27:19 UTC
-->

# Packaging and service deployment

## Linux (`systemd`)

Files:

- `deploy/systemd/4ham-spectrum-analysis.service`
- `deploy/systemd/install-systemd.sh`

### Install

1. Ensure the project virtual environment exists in `<project_dir>/.venv`.
2. Run:

```bash
bash deploy/systemd/install-systemd.sh <project_dir> <linux_user> [service_name]
```

Example:

```bash
bash deploy/systemd/install-systemd.sh /opt/4ham-spectrum-analysis octavio 4ham-spectrum-analysis
```

Default runtime behavior in service template:

- Backend binds `0.0.0.0:8000`
- WSJT-X UDP ingest enabled (`WSJTX_UDP_ENABLE=1`)
- WSJT-X autostart disabled (`WSJTX_AUTOSTART=0`) for headless/server mode
- Direwolf KISS enabled + autostart

## Windows service

File:

- `deploy/windows/install-service.ps1`

### Install (PowerShell as Administrator)

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\windows\install-service.ps1 -ProjectDir "C:\4ham-spectrum-analysis" -ServiceName "4ham-spectrum-analysis"
```

Notes:

- Script creates an auto-start service running `uvicorn`.
- Script sets machine-level env vars for decoder ingest/autostart.
- Confirm with:

```powershell
sc.exe query 4ham-spectrum-analysis
```
