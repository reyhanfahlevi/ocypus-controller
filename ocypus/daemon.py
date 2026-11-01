"""
Ocypus Controller Daemon loop.
Coordinates hardware sensors and USB HID packet dispatching.
"""

import time
import signal
import sys
import logging
from typing import Optional

from .protocol import OcypusPacketBuilder
from .device import find_ocypus_devices, HidDevice
from .config import Config
from .sensors import CpuSensor, MemorySensor, GpuSensor

logger = logging.getLogger("ocypus.daemon")


class OcypusDaemon:
    def __init__(self, config: Config):
        self.config = config
        self.running = False
        self.cpu_sensor = CpuSensor(
            hwmon_temp_path=config.custom_temp_path,
            hwmon_fan_path=config.custom_fan_path,
        )
        self.mem_sensor = MemorySensor()
        self.gpu_sensor = GpuSensor()
        self.active_device: Optional[HidDevice] = None
        self.consecutive_errors = 0
        self.max_retries = 5

    def start(self):
        self.running = True
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        logger.info("Ocypus controller daemon started on Linux/Proxmox 9")
        logger.info(
            "Config: mode=%s, unit=%s, interval=%.1fs, cycle=%ds",
            self.config.display_mode_str,
            self.config.temp_unit,
            self.config.refresh_interval,
            self.config.cycle_interval,
        )

        while self.running:
            try:
                if self.active_device is None:
                    devices = find_ocypus_devices()
                    if not devices:
                        logger.warning("No Ocypus/Hongtai controller found. Retrying in 3s...")
                        time.sleep(3.0)
                        continue
                    self.active_device = devices[0]
                    self.active_device.open()
                    logger.info("Connected to %s (%s)", self.active_device.name, self.active_device.path)
                    self.consecutive_errors = 0

                self._tick()
                self.consecutive_errors = 0
                time.sleep(self.config.refresh_interval)

            except (BrokenPipeError, OSError) as e:
                self.consecutive_errors += 1
                if self.consecutive_errors >= self.max_retries:
                    logger.error(
                        "Device communication error (%d/%d): %s. Reconnecting...",
                        self.consecutive_errors,
                        self.max_retries,
                        e,
                    )
                    if self.active_device:
                        self.active_device.close()
                        self.active_device = None
                    self.consecutive_errors = 0
                    time.sleep(2.0)
                else:
                    logger.warning(
                        "Device communication error (%d/%d): %s. Retrying...",
                        self.consecutive_errors,
                        self.max_retries,
                        e,
                    )
                    time.sleep(0.2)
            except Exception as e:
                logger.exception("Unexpected error in daemon loop: %s", e)
                time.sleep(1.0)

        self._cleanup()

    def _tick(self):
        # 1. Collect CPU metrics
        cpu_temp = self.cpu_sensor.get_temperature()
        cpu_util = self.cpu_sensor.get_utilization()
        cpu_freq = self.cpu_sensor.get_frequency_mhz()
        cpu_power = self.cpu_sensor.get_power_w()
        fan_rpm = self.cpu_sensor.get_fan_rpm()

        # 2. Collect Memory metrics
        mem_util, mem_temp, mem_freq = self.mem_sensor.get_metrics()

        # 3. Collect GPU metrics
        gpu_temp, gpu_util, gpu_freq, gpu_power = self.gpu_sensor.get_metrics()

        # 4. Determine metric to display on numerical displays
        if self.config.is_power_mode:
            target_val = gpu_power if self.config.show_gpu else cpu_power
            is_temp = False
            metric_name = "Power"
            unit_str = "W"
        elif self.config.is_util_mode:
            target_val = gpu_util if self.config.show_gpu else cpu_util
            is_temp = False
            metric_name = "Util"
            unit_str = "%"
        elif self.config.is_ram_mode:
            target_val = mem_util
            is_temp = False
            metric_name = "RAM"
            unit_str = "%"
        elif self.config.is_cycle_mode:
            metrics = self.config.cycle_metrics or ["temp", "util", "watt"]
            cycle_phase = int(time.time() // max(1, self.config.cycle_interval)) % len(metrics)
            current_metric = metrics[cycle_phase].lower()
            if "temp" in current_metric:
                target_val = gpu_temp if self.config.show_gpu else cpu_temp
                is_temp = True
                metric_name = "Temp"
                unit_str = "°F" if self.config.use_fahrenheit else "°C"
            elif any(k in current_metric for k in ("util", "load", "percent")):
                target_val = gpu_util if self.config.show_gpu else cpu_util
                is_temp = False
                metric_name = "Util"
                unit_str = "%"
            elif any(k in current_metric for k in ("watt", "power")):
                target_val = gpu_power if self.config.show_gpu else cpu_power
                is_temp = False
                metric_name = "Power"
                unit_str = "W"
            elif "ram" in current_metric or "mem" in current_metric:
                target_val = mem_util
                is_temp = False
                metric_name = "RAM"
                unit_str = "%"
            else:
                target_val = gpu_temp if self.config.show_gpu else cpu_temp
                is_temp = True
                metric_name = "Temp"
                unit_str = "°F" if self.config.use_fahrenheit else "°C"
        else:
            target_val = gpu_temp if self.config.show_gpu else cpu_temp
            is_temp = True
            metric_name = "Temp"
            unit_str = "°F" if self.config.use_fahrenheit else "°C"

        # 5. Build and send packet
        if self.active_device.vid == 0x1A2C and self.active_device.pid == 0x434D:
            # YCC Custom variant
            packet = OcypusPacketBuilder.build_ycc_packet(
                val=target_val,
                show_gpu=self.config.show_gpu,
                use_fahrenheit=self.config.use_fahrenheit,
                is_temp=is_temp,
            )
        else:
            # Standard 64-byte Hongtai/Ocypus packet
            packet = OcypusPacketBuilder.build_standard_packet(
                cpu_temp=cpu_temp,
                cpu_util=cpu_util,
                cpu_freq_mhz=cpu_freq,
                cpu_power_w=cpu_power,
                gpu_temp=gpu_temp,
                gpu_util=gpu_util,
                gpu_freq_mhz=gpu_freq,
                gpu_power_w=gpu_power,
                cpu_fan_rpm=fan_rpm,
                chassis_fan_rpm=0,
                ram_util=mem_util,
                ram_temp=mem_temp,
                ram_freq_mhz=mem_freq,
                display_mode=self.config.display_mode_code,
                cycle_interval=self.config.cycle_interval,
                use_fahrenheit=self.config.use_fahrenheit,
                show_gpu=self.config.show_gpu,
            )

        bytes_written = self.active_device.write(packet)
        if bytes_written is not None and bytes_written < 0:
            raise OSError(f"Device write failed with code {bytes_written}")
        logger.debug(
            "Update sent: %s=%.1f%s (CPU=%.1f°C/%.1fW, GPU=%.1f°C/%.1fW, RAM=%.1f%%)",
            metric_name,
            target_val,
            unit_str,
            cpu_temp,
            cpu_power,
            gpu_temp,
            gpu_power,
            mem_util,
        )

    def _handle_signal(self, signum, frame):
        logger.info("Shutdown signal received (%s), exiting...", signum)
        self.running = False

    def _cleanup(self):
        if self.active_device:
            self.active_device.close()
            self.active_device = None
        logger.info("Ocypus daemon cleanly stopped.")
