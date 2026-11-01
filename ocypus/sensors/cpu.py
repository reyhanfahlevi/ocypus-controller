"""
Linux CPU Metrics Collector for Proxmox 9 (Debian-based).
Collects: Temperature, Utilization %, Frequency (MHz), Power Draw (W), Fan Speed (RPM).
"""

import os
import glob
import time
from typing import Optional, Tuple


class CpuSensor:
    def __init__(
        self,
        hwmon_temp_path: Optional[str] = None,
        hwmon_fan_path: Optional[str] = None,
    ):
        self._custom_temp_path = hwmon_temp_path
        self._custom_fan_path = hwmon_fan_path
        self._temp_path: Optional[str] = None
        self._power_path: Optional[str] = None
        self._power_type: str = "none"  # "rapl", "hwmon_energy", "hwmon_power"
        self._prev_energy_uj: Optional[int] = None
        self._prev_energy_time: Optional[float] = None
        self._prev_stat: Optional[Tuple[int, int]] = None  # (idle, total)
        self._fan_path: Optional[str] = None

        self._discover_paths()

    def _discover_paths(self):
        hwmon_dirs = sorted(glob.glob("/sys/class/hwmon/hwmon*"))
        self._discover_temp_path(hwmon_dirs)
        self._discover_fan_path(hwmon_dirs)
        self._discover_power_path(hwmon_dirs)

    def _discover_temp_path(self, hwmon_dirs):
        if self._custom_temp_path and os.path.exists(self._custom_temp_path):
            self._temp_path = self._custom_temp_path
            return

        best_temp = None
        for d in hwmon_dirs:
            name_file = os.path.join(d, "name")
            driver_name = ""
            if os.path.exists(name_file):
                try:
                    with open(name_file, "r") as f:
                        driver_name = f.read().strip().lower()
                except Exception:
                    pass

            if driver_name in ("k10temp", "zenpower", "coretemp", "cpu_thermal"):
                inputs = sorted(glob.glob(os.path.join(d, "temp*_input")))
                for inp in inputs:
                    label_file = inp.replace("_input", "_label")
                    if os.path.exists(label_file):
                        try:
                            with open(label_file, "r") as f:
                                label = f.read().strip().lower()
                            if "tctl" in label or "package" in label or "tdie" in label:
                                best_temp = inp
                                break
                        except Exception:
                            pass
                if best_temp:
                    break
                if inputs:
                    best_temp = inputs[0]
                    break

            if not best_temp:
                inputs = glob.glob(os.path.join(d, "temp*_input"))
                if inputs:
                    best_temp = inputs[0]

        self._temp_path = best_temp

    def _discover_fan_path(self, hwmon_dirs):
        if self._custom_fan_path and os.path.exists(self._custom_fan_path):
            self._fan_path = self._custom_fan_path
            return

        candidate_fans = []
        for d in hwmon_dirs:
            for fan_file in sorted(glob.glob(os.path.join(d, "fan*_input"))):
                label_file = fan_file.replace("_input", "_label")
                label = ""
                if os.path.exists(label_file):
                    try:
                        with open(label_file, "r") as f:
                            label = f.read().strip().lower()
                    except Exception:
                        pass

                rpm = 0
                try:
                    with open(fan_file, "r") as f:
                        rpm = int(f.read().strip())
                except Exception:
                    pass

                candidate_fans.append((fan_file, label, rpm))

        # Prioritize:
        # 1. Label containing "cpu" or "pump" or "cooler" or "aio" with rpm > 0
        for fpath, label, rpm in candidate_fans:
            if any(k in label for k in ("cpu", "pump", "aio", "cooler")) and rpm > 0:
                self._fan_path = fpath
                return

        # 2. First fan with active RPM > 0 (e.g. AIO pump or CPU fan header)
        for fpath, label, rpm in candidate_fans:
            if rpm > 0:
                self._fan_path = fpath
                return

        # 3. Any found fan input
        if candidate_fans:
            self._fan_path = candidate_fans[0][0]

    def _discover_power_path(self, hwmon_dirs):
        # 1. Intel RAPL
        rapl_paths = [
            "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj",
            "/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0/energy_uj",
        ]
        for rp in rapl_paths:
            if os.path.exists(rp):
                self._power_path = rp
                self._power_type = "rapl"
                return

        # 2. AMD energy or hwmon energy/power (e.g. zenpower, amd_energy)
        for d in hwmon_dirs:
            # Direct power in microWatts
            for p_name in ("power1_average", "power1_input", "power2_average", "power2_input"):
                p_file = os.path.join(d, p_name)
                if os.path.exists(p_file):
                    self._power_path = p_file
                    self._power_type = "hwmon_power"
                    return

            # Accumulated energy in microJoules
            for e_name in ("energy1_input", "energy2_input"):
                e_file = os.path.join(d, e_name)
                if os.path.exists(e_file):
                    self._power_path = e_file
                    self._power_type = "hwmon_energy"
                    return

    def get_temperature(self) -> float:
        if not self._temp_path or not os.path.exists(self._temp_path):
            self._discover_paths()

        if self._temp_path and os.path.exists(self._temp_path):
            try:
                with open(self._temp_path, "r") as f:
                    val = float(f.read().strip())
                    return val / 1000.0 if val > 200 else val
            except Exception:
                pass
        return 0.0

    def get_utilization(self) -> float:
        """Calculates total CPU utilization % from /proc/stat."""
        try:
            with open("/proc/stat", "r") as f:
                first_line = f.readline()
            fields = [int(x) for x in first_line.split()[1:]]
            idle = fields[3] + fields[4]  # idle + iowait
            total = sum(fields)

            if self._prev_stat is None:
                self._prev_stat = (idle, total)
                # Quick 50ms sample for one-shot CLI commands
                time.sleep(0.05)
                with open("/proc/stat", "r") as f:
                    second_line = f.readline()
                fields2 = [int(x) for x in second_line.split()[1:]]
                idle2 = fields2[3] + fields2[4]
                total2 = sum(fields2)
                d_idle = idle2 - idle
                d_total = total2 - total
                if d_total > 0:
                    return max(0.0, min(100.0, 100.0 * (1.0 - (d_idle / d_total))))
                return 0.0

            prev_idle, prev_total = self._prev_stat
            self._prev_stat = (idle, total)

            delta_idle = idle - prev_idle
            delta_total = total - prev_total

            if delta_total > 0:
                util = 100.0 * (1.0 - (delta_idle / delta_total))
                return max(0.0, min(100.0, util))
        except Exception:
            pass
        return 0.0

    def get_frequency_mhz(self) -> float:
        """Returns average frequency in MHz across CPU cores."""
        freqs = []
        freq_files = glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")
        if freq_files:
            for ff in freq_files:
                try:
                    with open(ff, "r") as f:
                        freqs.append(float(f.read().strip()) / 1000.0)
                except Exception:
                    pass
        elif os.path.exists("/proc/cpuinfo"):
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("cpu MHz"):
                            freqs.append(float(line.split(":")[1].strip()))
            except Exception:
                pass

        if freqs:
            return sum(freqs) / len(freqs)
        return 0.0

    def get_power_w(self) -> float:
        """Calculates CPU power in Watts from RAPL or hwmon."""
        if not self._power_path or not os.path.exists(self._power_path):
            self._discover_paths()

        if not self._power_path or not os.path.exists(self._power_path):
            return 0.0

        now = time.time()
        try:
            with open(self._power_path, "r") as f:
                raw_val = int(f.read().strip())

            # Direct power sensors (e.g. zenpower power1_average / power1_input in uW)
            if self._power_type == "hwmon_power":
                return raw_val / 1_000_000.0

            # Cumulative energy sensors (Intel RAPL energy_uj or AMD energy1_input)
            if self._power_type in ("rapl", "hwmon_energy"):
                if self._prev_energy_uj is not None and self._prev_energy_time is not None:
                    delta_energy_uj = raw_val - self._prev_energy_uj
                    delta_t = now - self._prev_energy_time
                    self._prev_energy_uj = raw_val
                    self._prev_energy_time = now

                    if delta_t > 0 and delta_energy_uj >= 0:
                        # 1 uJ / 1s = 1e-6 W
                        return (delta_energy_uj / 1_000_000.0) / delta_t
                else:
                    # Initial call: do a quick 80ms delta measurement for CLI commands
                    self._prev_energy_uj = raw_val
                    self._prev_energy_time = now
                    time.sleep(0.08)
                    now2 = time.time()
                    with open(self._power_path, "r") as f:
                        raw_val2 = int(f.read().strip())
                    delta_t = now2 - now
                    delta_e = raw_val2 - raw_val
                    if delta_t > 0 and delta_e >= 0:
                        self._prev_energy_uj = raw_val2
                        self._prev_energy_time = now2
                        return (delta_e / 1_000_000.0) / delta_t
        except PermissionError:
            # Linux RAPL energy_uj has 0400 permissions (root required)
            pass
        except Exception:
            pass
        return 0.0

    def get_fan_rpm(self) -> int:
        if self._fan_path and os.path.exists(self._fan_path):
            try:
                with open(self._fan_path, "r") as f:
                    return int(f.read().strip())
            except Exception:
                pass
        return 0
