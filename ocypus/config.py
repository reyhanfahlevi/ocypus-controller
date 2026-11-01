"""
Configuration loader and validator for Ocypus Linux Controller.
"""

import json
import os
from typing import Dict, Any

DEFAULT_CONFIG: Dict[str, Any] = {
    "temp_unit": "celsius",          # "celsius" or "fahrenheit"
    "display_mode": "temp",          # "temp", "util", "cycle", "ram", "power", "watt"
    "cycle_interval": 5,             # seconds between cycles
    "refresh_interval": 1.0,         # update frequency in seconds (default 1s)
    "show_gpu": False,               # show GPU instead of CPU
    "custom_temp_path": None,        # optional path to custom hwmon temp file
}

CONFIG_PATHS = [
    "/etc/ocypus/config.json",
    os.path.expanduser("~/.config/ocypus/config.json"),
    "config.json",
]


class Config:
    def __init__(self, data: Dict[str, Any]):
        self.temp_unit = data.get("temp_unit", DEFAULT_CONFIG["temp_unit"]).lower()
        self.display_mode_str = data.get("display_mode", DEFAULT_CONFIG["display_mode"]).lower()
        self.cycle_interval = int(data.get("cycle_interval", DEFAULT_CONFIG["cycle_interval"]))
        self.refresh_interval = float(data.get("refresh_interval", DEFAULT_CONFIG["refresh_interval"]))
        self.show_gpu = bool(data.get("show_gpu", DEFAULT_CONFIG["show_gpu"]))
        self.custom_temp_path = data.get("custom_temp_path", None)

    @property
    def use_fahrenheit(self) -> bool:
        return self.temp_unit.startswith("f")

    @property
    def is_power_mode(self) -> bool:
        return any(k in self.display_mode_str for k in ("power", "watt"))

    @property
    def is_util_mode(self) -> bool:
        return any(k in self.display_mode_str for k in ("util", "load", "percent"))

    @property
    def is_ram_mode(self) -> bool:
        return "ram" in self.display_mode_str or "mem" in self.display_mode_str

    @property
    def is_cycle_mode(self) -> bool:
        return "cycle" in self.display_mode_str

    @property
    def display_mode_code(self) -> int:
        if self.is_power_mode:
            return 1  # Map to secondary metric mode on standard hardware
        elif self.is_util_mode:
            return 1
        elif self.is_cycle_mode or self.is_ram_mode:
            return 2
        return 0  # temp

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        if path and os.path.exists(path):
            with open(path, "r") as f:
                return cls({**DEFAULT_CONFIG, **json.load(f)})

        for p in CONFIG_PATHS:
            if os.path.exists(p):
                try:
                    with open(p, "r") as f:
                        return cls({**DEFAULT_CONFIG, **json.load(f)})
                except Exception:
                    pass

        return cls(DEFAULT_CONFIG)
