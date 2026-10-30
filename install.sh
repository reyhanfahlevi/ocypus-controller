#!/usr/bin/env bash
#
# Ocypus Linux Controller Installer for Proxmox VE 9 / Debian
#

set -e

if [ "$EUID" -ne 0 ]; then
  echo "[-] Please run as root (e.g. sudo bash install.sh)"
  exit 1
fi

echo "[+] Installing Ocypus Linux Controller..."

INSTALL_DIR="/opt/ocypus-controller"
CONFIG_DIR="/etc/ocypus"

# Ensure python3 is available
if ! command -v python3 &>/dev/null; then
  echo "[-] python3 is required. Installing via apt..."
  apt-get update && apt-get install -y python3
fi

# 1. Create installation directories
echo "[+] Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"

# 2. Copy source code
echo "[+] Copying application files to $INSTALL_DIR..."
cp -r ocypus "$INSTALL_DIR/"

# 3. Create CLI wrapper in /usr/local/bin
echo "[+] Creating /usr/local/bin/ocypus-ctl..."
cat << 'EOF' > /usr/local/bin/ocypus-ctl
#!/usr/bin/env bash
PYTHONPATH="/opt/ocypus-controller:${PYTHONPATH}" exec /usr/bin/python3 -m ocypus.cli "$@"
EOF
chmod +x /usr/local/bin/ocypus-ctl

# 4. Install default configuration if none exists
if [ ! -f "$CONFIG_DIR/config.json" ]; then
  echo "[+] Installing default configuration to $CONFIG_DIR/config.json..."
  cp config/ocypus.conf.example.json "$CONFIG_DIR/config.json"
fi

# 5. Install udev rules
echo "[+] Installing udev rules..."
cp config/99-ocypus.rules /etc/udev/rules.d/
if command -v udevadm &>/dev/null; then
  udevadm control --reload-rules && udevadm trigger || true
fi

# 6. Install systemd service
echo "[+] Installing systemd service..."
cat << 'EOF' > /etc/systemd/system/ocypus.service
[Unit]
Description=Ocypus Digital Display Controller Daemon
After=network.target sys-subsystem-net-devices.target

[Service]
Type=simple
User=root
Environment="PYTHONPATH=/opt/ocypus-controller"
ExecStart=/usr/bin/python3 -m ocypus.cli daemon
Restart=always
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ocypus.service
systemctl restart ocypus.service || true

echo ""
echo "[✓] Installation complete!"
echo "    - CLI Tool:      ocypus-ctl (detect, status, run)"
echo "    - Config file:   /etc/ocypus/config.json"
echo "    - Systemd unit:  systemctl status ocypus"
echo "    - View logs:     journalctl -u ocypus -f"
echo ""
echo "Try running: ocypus-ctl detect"
