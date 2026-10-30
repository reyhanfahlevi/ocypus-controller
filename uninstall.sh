#!/usr/bin/env bash
#
# Ocypus Linux Controller Uninstaller
#

set -e

if [ "$EUID" -ne 0 ]; then
  echo "[-] Please run as root (sudo bash uninstall.sh)"
  exit 1
fi

echo "[+] Stopping and disabling ocypus.service..."
systemctl stop ocypus.service 2>/dev/null || true
systemctl disable ocypus.service 2>/dev/null || true

echo "[+] Removing service and udev files..."
rm -f /etc/systemd/system/ocypus.service
rm -f /etc/udev/rules.d/99-ocypus.rules
systemctl daemon-reload
udevadm control --reload-rules 2>/dev/null || true

echo "[+] Removing installation directory and CLI binary..."
rm -rf /opt/ocypus-controller
rm -f /usr/local/bin/ocypus-ctl

echo "[?] Do you want to remove configuration (/etc/ocypus)? [y/N]"
read -r response
if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
  rm -rf /etc/ocypus
  echo "[+] Configuration removed."
else
  echo "[+] Keeping /etc/ocypus."
fi

echo "[✓] Ocypus Linux Controller uninstalled successfully."
