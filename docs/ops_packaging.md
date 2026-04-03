<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-04-03 UTC
-->

# Packaging and Service Deployment

## Recommended Path (Linux `systemd`)

Use the repository service helper script:

- `scripts/install_systemd_service.sh`
- `scripts/4ham-spectrum-analysis.service.template`

### Install

```bash
./scripts/install_systemd_service.sh install
```

### Operations

```bash
./scripts/install_systemd_service.sh status
./scripts/install_systemd_service.sh logs
./scripts/install_systemd_service.sh restart
./scripts/install_systemd_service.sh stop
```

### Service-only uninstall

```bash
./scripts/install_systemd_service.sh uninstall
```

### Environment defaults file

The helper creates/uses:

```text
/etc/default/4ham-spectrum-analysis
```

Common keys:

- `APP_HOST`
- `APP_PORT`
- `FT_EXTERNAL_ENABLE`
- `FT_EXTERNAL_MODES`
- `DIREWOLF_KISS_ENABLE`
- `DIREWOLF_AUTOSTART`
- `DIREWOLF_CMD`

## Full project uninstall (service + environments + optional purge)

Use the repository root uninstaller:

```bash
./uninstall.sh
./uninstall.sh --purge-data
./uninstall.sh --purge-system-packages
./uninstall.sh --purge-all --yes
```

Note: unlike `install_systemd_service.sh uninstall`, the root `uninstall.sh` also removes `/etc/default/4ham-spectrum-analysis`.

## Legacy/advanced deploy helper (optional)

These files remain available for custom packaging flows:

- `deploy/systemd/4ham-spectrum-analysis.service`
- `deploy/systemd/install-systemd.sh`

Usage:

```bash
bash deploy/systemd/install-systemd.sh <project_dir> <linux_user> [service_name]
```

Example:

```bash
bash deploy/systemd/install-systemd.sh /opt/4ham-spectrum-analysis octavio 4ham-spectrum-analysis
```


