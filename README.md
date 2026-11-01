# Ocypus Digital Controller for Linux & Proxmox 9

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Proxmox%20VE%209-orange.svg)](#)
[![Python](https://img.shields.io/badge/Python-3.9%2B-green.svg)](#)
[![Dependencies](https://img.shields.io/badge/Dependencies-Zero%20External-brightgreen.svg)](#)

A lightweight, zero-dependency native Linux daemon and CLI controller for **Ocypus Digital** hardware display coolers (e.g. Ocypus Iota, Delta, and Hongtai OEM digital coolers).

> [!IMPORTANT]
> ### ⚠️ Reverse Engineering Statement & Disclaimer
> This project is the result of clean-room reverse engineering of the proprietary Windows software `Ocypus Digital Elite 2.0.6.exe` (developed by Dongguan Hongtai Technology Co., Ltd. for Ocypus hardware).
>
> - **Purpose & Interoperability**: Created exclusively for interoperability, allowing users on Linux, Proxmox VE 8/9, and other headless server distributions to display real-time system metrics on their hardware screen where no official Linux software exists.
> - **Non-Affiliation**: This repository is an independent, community-driven project and is **not** affiliated with, endorsed by, or sponsored by Ocypus or Dongguan Hongtai Technology Co., Ltd.
> - **Trademarks**: All brand names, trademarks, and logos belong to their respective owners and are referenced here strictly for identification and hardware compatibility purposes.

---

## ⚡ Highlights

- **Headless & Ultra-Lightweight**: No Electron, X11, or GUI dependencies. Runs as a background `systemd` daemon using ~15MB RAM and 0.05% CPU.
- **Zero Python/C Build Dependencies**: Uses the native Linux kernel `/dev/hidraw` subsystem directly. Runs on standard Python 3.9+ without compiling C extensions (`node-gyp`, `libusb`, or `gcc`).
- **Proxmox VE 8/9 & Debian Native**: Automatically scans Linux `hwmon` (`coretemp`, `k10temp`, `zenpower`) for CPU temperatures, `/proc/stat` for utilization, RAPL for power consumption (W), and `/proc/meminfo` for memory.
- **GPU & Fan Support**: Automatic detection of NVIDIA GPUs (`nvidia-smi`) and AMD/Intel GPUs (`amdgpu` hwmon).
- **Automated udev & Systemd Setup**: Includes one-click `install.sh` and `uninstall.sh`.

---

## 🔍 Reverse Engineering Findings & Protocol Specification

The Windows application `Ocypus Digital Elite 2.0.6.exe` was analyzed to discover how the host system communicates with the cooler's internal MCU over USB HID.

### 1. Supported Devices & USB Identifiers

| Device Model | VID | PID | Interface / Notes |
| :--- | :--- | :--- | :--- |
| **Ocypus Digital (Standard)** | `0x5131` | `0x2016` | USB HID 64-byte report (0x01) |
| **Ocypus Digital (YCC Custom)** | `0x1A2C` | `0x434D` | USB HID 64-byte padded BCD report (Usage Page 0xFF01, Interface 1) |
| **Hongtai Public Edition** | `0x5131` | `0x2007` | Standard 64-byte HID |
| **YiCheng / Alseye / RuiTuo / Cooling** | `0x5131` | `0x2008`..`0x200B`| Standard 64-byte HID |
| **MSI / CoolMai / TT Segment** | `0x5131` | `0x200C`..`0x200E`| Standard 64-byte HID |
| **SAMA / 1stPlayer** | `0x5131` | `0x2018`, `0x2019` | Standard 64-byte HID |

### 2. Standard 64-Byte HID Packet Structure

Data is transmitted every **1,000 ms** (1 second) as a 64-byte HID output report:

| Byte Index | Field Name | Type | Description |
| :---: | :--- | :---: | :--- |
| **0** | `Report ID` | `uint8` | Always `0x01` |
| **1** | `Reserved` | `uint8` | Always `0x00` |
| **2** | `Header 1` | `uint8` | Always `0x01` |
| **3** | `Header 2` | `uint8` | Always `0x02` |
| **4** | `CPU Temp Integer` | `uint8` | Temperature integer (e.g. `45` for 45°C) |
| **5** | `CPU Temp Decimal` | `uint8` | Fraction × 100 (e.g. `50` for .5°C) |
| **6** | `Temp Unit` | `uint8` | `0` = Celsius (°C), `1` = Fahrenheit (°F) |
| **7** | `CPU Utilization` | `uint8` | CPU usage percent (`0`..`100`) |
| **8** | `CPU Power Low` | `uint8` | CPU Power Draw (Watts) `% 100` |
| **9** | `CPU Power Dec` | `uint8` | CPU Power fraction × 100 |
| **10** | `CPU Freq High` | `uint8` | CPU Core Frequency (MHz) `/ 100` |
| **11** | `CPU Freq Low` | `uint8` | CPU Core Frequency (MHz) `% 100` |
| **12..13**| `CPU Voltage` | `uint8[2]`| Voltage integer & fraction × 100 |
| **14** | `GPU Temp Integer` | `uint8` | GPU Temperature integer |
| **15** | `GPU Temp Decimal` | `uint8` | GPU Temperature fraction × 100 |
| **16** | `GPU Temp Unit` | `uint8` | `0` = Celsius, `1` = Fahrenheit |
| **17** | `GPU Utilization` | `uint8` | GPU usage percent (`0`..`100`) |
| **18..19**| `GPU Power` | `uint8[2]`| GPU Power (W) `% 100` and fraction × 100 |
| **20..21**| `GPU Freq` | `uint8[2]`| GPU Frequency (MHz) `/ 100` and `% 100` |
| **22..23**| `CPU Fan RPM` | `uint8[2]`| CPU Fan Speed `/ 100` and `% 100` |
| **24..25**| `Chassis Fan RPM`| `uint8[2]`| Chassis Fan Speed `/ 100` and `% 100` |
| **26** | `Century` | `uint8` | High century digits (e.g. `20` for 2026) |
| **27** | `Year` | `uint8` | Low year digits (e.g. `26` for 2026) |
| **28** | `Month` | `uint8` | Month (`1`..`12`) |
| **29** | `Day` | `uint8` | Day of Month (`1`..`31`) |
| **30..32**| `Time` | `uint8[3]`| Hour (`0`..`23`), Minute, Second |
| **33** | `Day of Week` | `uint8` | `0` = Sunday, `1` = Monday ... `6` = Saturday |
| **34** | `RAM Utilization` | `uint8` | Memory usage percent (`0`..`100`) |
| **35** | `CPU Power High` | `uint8` | CPU Power Draw (W) `/ 100` (hundreds digit) |
| **36** | `GPU Power High` | `uint8` | GPU Power Draw (W) `/ 100` (hundreds digit) |
| **37** | `Display Mode` | `uint8` | `0` = Temp, `1` = Utilization, `2` = Cycle |
| **38** | `Cycle Interval` | `uint8` | Interval in seconds for cycling mode (default `5`) |
| **39** | `CPU/GPU Flag` | `uint8` | `0` = Show CPU, `1` = Show GPU |
| **40** | `Sensor Mask` | `uint8` | Bitmask: `1`=CPU temp, `2`=CPU util, `4`=GPU temp, `8`=GPU util |
| **41..42**| `Display Mode` | `uint8[2]`| Secondary display mode flags |
| **43..45**| `RAM Temp & Unit`| `uint8[3]`| RAM Temp int, fraction, and unit (`0`=C, `1`=F) |
| **46..47**| `RAM Frequency` | `uint8[2]`| RAM Frequency (MHz) `/ 100` and `% 100` |
| **48** | `Display Mode` | `uint8` | `0`=CPU, `1`=GPU, `2`=RAM, `3`=Cycle |
| **49..51**| `Decimals` | `uint8[3]`| Decimal fractions for CPU, GPU, and RAM |
| **52..63**| `Padding` | `uint8[12]`| Zero padding (`0x00`) to 64 bytes total |

### 3. YCC Custom HID Packet Structure (VID `0x1A2C`, PID `0x434D`)

The China Resource Semico MCU uses Report ID `0x07` on Interface 1 (`Usage Page 0xFF01`) with a report count of 63 bytes (64 bytes total). 

```
Byte 0      : Report ID (0x07)
Byte 1..2   : Header (0xFF, 0xFF)
Byte 3      : Hundreds Digit (0..9 BCD)
Byte 4      : Tens Digit (0..9 BCD)
Byte 5      : Ones Digit (0..9 BCD)
Byte 6..63  : Zero Padding (0x00 * 58)
```
*(Note: Omitting the 58-byte padding triggers a USB STALL / Broken Pipe on Linux).*

---

## 🚀 Installation on Proxmox VE 9 / Debian

### 1. Clone Repository to Proxmox Host

```bash
git clone https://github.com/reyhanfahlevi/ocypus-controller.git /opt/ocypus-src
cd /opt/ocypus-src
```

### 2. Run the Installer

```bash
sudo bash install.sh
```

The installer will:
1. Verify Python 3 is installed.
2. Install the daemon package into `/opt/ocypus-controller`.
3. Create the `/usr/local/bin/ocypus-ctl` command.
4. Install udev permissions in `/etc/udev/rules.d/99-ocypus.rules`.
5. Install and start the `systemd` service `ocypus.service`.

---

## 🛠️ CLI Usage & Diagnostics

### Detect Connected Hardware & Proxmox Sensors
```bash
ocypus-ctl detect
```
Example output:
```text
=== Scanning for Ocypus & Hongtai USB Hardware ===
[1] Ocypus Digital Display (Standard)
    Path:    /dev/hidraw3
    VID:PID: 0x5131:0x2016

=== Detecting System Sensors (Proxmox / Linux) ===
CPU Temp Path: /sys/class/hwmon/hwmon1/temp1_input (k10temp Tctl)
CPU Temp:      42.5 °C
CPU Util:      3.2 %
CPU Freq:      3800.0 MHz
CPU Power:     65.4 W
CPU Fan RPM:   1250 RPM
Memory Util:   14.8 %
GPU Temp:      0.0 °C
```

### Inspect Live Status & Generated 64-Byte Packet
```bash
ocypus-ctl status
```

### Run in Foreground (Testing)
```bash
# Display CPU temperature in Celsius
ocypus-ctl run

# Display in Fahrenheit and cycle between Temp and Utilization every 5s
ocypus-ctl run --temp-unit fahrenheit --display-mode cycle -v
```

---

## ⚙️ Configuration (`/etc/ocypus/config.json`)

Edit `/etc/ocypus/config.json` to customize behavior:

```json
{
  "temp_unit": "celsius",
  "display_mode": "temp",
  "cycle_interval": 5,
  "cycle_metrics": ["temp", "util", "watt"],
  "refresh_interval": 1.0,
  "show_gpu": false,
  "custom_temp_path": null,
  "custom_fan_path": null
}
```

- `temp_unit`: `"celsius"` or `"fahrenheit"`.
- `display_mode`:
  - `"temp"`: Static CPU/GPU temperature display.
  - `"util"`: Static CPU/GPU utilization (%) display.
  - `"watt"` / `"power"`: Static CPU/GPU power draw in Watts (W) via Intel RAPL or GPU sensor.
  - `"ram"`: Static memory utilization (%) display.
  - `"cycle"`: Alternates automatically through metrics in `cycle_metrics`.
- `cycle_interval`: Number of seconds to display each metric in cycle mode (default: `5`).
- `cycle_metrics`: Array of metrics to rotate through during cycle mode (e.g. `["temp", "util", "watt"]`).
- `refresh_interval`: Send interval in seconds (default: `1.0`).
- `show_gpu`: Set `true` to display GPU metrics instead of CPU.
- `custom_temp_path`: Explicit `/sys/class/hwmon/hwmonX/tempY_input` path if multiple sockets or sensors exist.
- `custom_fan_path`: Explicit `/sys/class/hwmon/hwmonX/fanY_input` path to override automatic fan header discovery.

After modifying the configuration, reload the service:
```bash
sudo systemctl restart ocypus
```

---

## 📋 Systemd Management

```bash
# Check service status
sudo systemctl status ocypus

# Follow real-time logs
sudo journalctl -u ocypus -f

# Stop or restart
sudo systemctl restart ocypus
sudo systemctl stop ocypus
```

---

## 🗑️ Uninstallation

To cleanly remove the controller and systemd service:

```bash
sudo bash /opt/ocypus-controller/uninstall.sh
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
