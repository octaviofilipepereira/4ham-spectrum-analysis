#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <project_dir> <linux_user> [service_name]"
  exit 1
fi

PROJECT_DIR="$1"
LINUX_USER="$2"
SERVICE_NAME="${3:-4ham-spectrum-analysis}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
TEMPLATE_PATH="${PROJECT_DIR}/deploy/systemd/4ham-spectrum-analysis.service"

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  echo "Template not found: $TEMPLATE_PATH"
  exit 1
fi

TMP_FILE="$(mktemp)"
cp "$TEMPLATE_PATH" "$TMP_FILE"
sed -i "s|REPLACE_USER|${LINUX_USER}|g" "$TMP_FILE"
sed -i "s|REPLACE_GROUP|${LINUX_USER}|g" "$TMP_FILE"
sed -i "s|REPLACE_PROJECT_DIR|${PROJECT_DIR}|g" "$TMP_FILE"

sudo cp "$TMP_FILE" "$SERVICE_PATH"
rm -f "$TMP_FILE"

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager
