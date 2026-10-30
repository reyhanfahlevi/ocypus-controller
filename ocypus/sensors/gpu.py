"""
Linux GPU Metrics Collector for Proxmox 9.
Supports: NVIDIA (via nvidia-smi / NVML) and AMD / Intel (via sysfs hwmon).
"""

import os
import glob
import subprocess
import shutil


class GpuSensor:
    def __init__(self):
        self._has_nvidia = shutil.which("nvidia-smi") is not None
        self._amd_hwmon = None
        self._discover_amd_intel()

    def _discover_amd_intel(self):
        # Look for amdgpu drm devices
        for card in glob.glob("/sys/class/drm/card*/device/hwmon/hwmon*"):
            self._amd_hwmon = card
            break

    def get_metrics(self) -> tuple[float, float, float, float]:
        """
        Returns (temp_c, util_pct, freq_mhz, power_w).
        """
        if self._has_nvidia:
            m = self._get_nvidia()
            if m:
                return m

        if self._amd_hwmon and os.path.exists(self._amd_hwmon):
            m = self._get_amd()
            if m:
                return m

        return (0.0, 0.0, 0.0, 0.0)

    def _get_nvidia(self) -> tuple[float, float, float, float] | None:
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=temperature.gpu,utilization.gpu,clocks.current.graphics,power.draw",
                "--format=csv,noheader,nounits",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1.0)
            if res.returncode == 0 and res.stdout.strip():
                line = res.stdout.strip().split("\n")[0]
                parts = [p.strip() for p in line.split(",")]
                temp_c = float(parts[0]) if len(parts) > 0 else 0.0
                util_pct = float(parts[1]) if len(parts) > 1 else 0.0
                freq_mhz = float(parts[2]) if len(parts) > 2 else 0.0
                power_w = float(parts[3]) if len(parts) > 3 else 0.0
                return (temp_c, util_pct, freq_mhz, power_w)
        except Exception:
            pass
        return None

    def _get_amd(self) -> tuple[float, float, float, float] | None:
        try:
            temp_c = 0.0
            util_pct = 0.0
            freq_mhz = 0.0
            power_w = 0.0

            # Temp
            t_file = os.path.join(self._amd_hwmon, "temp1_input")
            if os.path.exists(t_file):
                with open(t_file, "r") as f:
                    temp_c = float(f.read().strip()) / 1000.0

            # Power
            p_file = os.path.join(self._amd_hwmon, "power1_average")
            if os.path.exists(p_file):
                with open(p_file, "r") as f:
                    power_w = float(f.read().strip()) / 1_000_000.0

            # Util
            u_file = os.path.join(os.path.dirname(self._amd_hwmon), "gpu_busy_percent")
            if os.path.exists(u_file):
                with open(u_file, "r") as f:
                    util_pct = float(f.read().strip())

            return (temp_c, util_pct, freq_mhz, power_w)
        except Exception:
            pass
        return None
