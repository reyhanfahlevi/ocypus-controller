"""
Command line interface for Ocypus Controller Linux.
"""

import argparse
import logging
import sys
import os

from .config import Config
from .daemon import OcypusDaemon
from .device import find_ocypus_devices
from .sensors import CpuSensor, MemorySensor, GpuSensor
from .protocol import OcypusPacketBuilder


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_detect(args):
    print("=== Scanning for Ocypus & Hongtai USB Hardware ===")
    devices = find_ocypus_devices()
    if devices:
        for idx, dev in enumerate(devices, 1):
            up_str = f"0x{dev.usage_page:04X}" if dev.usage_page else "N/A"
            print(f"[{idx}] {dev.name}")
            print(f"    Path:       {dev.path}")
            print(f"    VID:PID:    0x{dev.vid:04X}:0x{dev.pid:04X}")
            print(f"    Usage Page: {up_str}")
    else:
        print("No supported USB HID display devices found.")
        print("Note: Ensure the USB header is plugged in, and check with 'lsusb'.")

    print("\n=== Detecting System Sensors (Proxmox / Linux) ===")
    cpu = CpuSensor()
    print(f"CPU Temp Path:  {cpu._temp_path or 'Not found'}")
    print(f"CPU Temp:       {cpu.get_temperature():.1f} °C")
    print(f"CPU Util:       {cpu.get_utilization():.1f} %")
    print(f"CPU Freq:       {cpu.get_frequency_mhz():.1f} MHz")
    print(f"CPU Power Path: {cpu._power_path or 'Not found (hint: run as sudo, or load intel_rapl_msr / zenpower)'}")
    print(f"CPU Power:      {cpu.get_power_w():.1f} W")
    print(f"CPU Fan Path:   {cpu._fan_path or 'Not found'}")
    print(f"CPU Fan RPM:    {cpu.get_fan_rpm()} RPM")

    mem = MemorySensor()
    mem_u, mem_t, mem_f = mem.get_metrics()
    print(f"Memory Util:   {mem_u:.1f} %")

    gpu = GpuSensor()
    gt, gu, gf, gp = gpu.get_metrics()
    print(f"GPU Temp:      {gt:.1f} °C")
    print(f"GPU Util:      {gu:.1f} %")
    print(f"GPU Power:     {gp:.1f} W")


def cmd_status(args):
    cfg = Config.load(args.config)
    devices = find_ocypus_devices()
    if not devices:
        print("Error: No Ocypus device detected.")
        sys.exit(1)

    dev = devices[0]
    print(f"Target: {dev.name} ({dev.path})")

    cpu = CpuSensor()
    mem = MemorySensor()
    gpu = GpuSensor()

    cpu_t = cpu.get_temperature()
    cpu_u = cpu.get_utilization()
    cpu_f = cpu.get_frequency_mhz()
    cpu_p = cpu.get_power_w()
    fan_rpm = cpu_sensor = cpu.get_fan_rpm()
    mem_u, mem_t, mem_f = mem.get_metrics()
    gt, gu, gf, gp = gpu.get_metrics()

    print(f"Sensor Readings:")
    print(f"  CPU: {cpu_t:.1f}°C, {cpu_u:.1f}%, {cpu_f:.0f}MHz, {cpu_p:.1f}W, Fan: {fan_rpm}RPM")
    print(f"  RAM: {mem_u:.1f}%")
    print(f"  GPU: {gt:.1f}°C, {gu:.1f}%, {gp:.1f}W")

    if dev.vid == 0x1A2C and dev.pid == 0x434D:
        if cfg.is_power_mode:
            target_val = gp if cfg.show_gpu else cpu_p
            is_temp = False
            mode_label = "Power (Watt)"
        elif cfg.is_util_mode:
            target_val = gu if cfg.show_gpu else cpu_u
            is_temp = False
            mode_label = "Utilization (%)"
        elif cfg.is_ram_mode:
            target_val = mem_u
            is_temp = False
            mode_label = "RAM (%)"
        else:
            target_val = gt if cfg.show_gpu else cpu_t
            is_temp = True
            mode_label = f"Temperature ({'°F' if cfg.use_fahrenheit else '°C'})"

        packet = OcypusPacketBuilder.build_ycc_packet(
            val=target_val,
            show_gpu=cfg.show_gpu,
            use_fahrenheit=cfg.use_fahrenheit,
            is_temp=is_temp,
        )
        print(f"\nGenerated 6-byte YCC HID Packet ({mode_label}: {target_val:.1f}):")
    else:
        packet = OcypusPacketBuilder.build_standard_packet(
            cpu_temp=cpu_t,
            cpu_util=cpu_u,
            cpu_freq_mhz=cpu_f,
            cpu_power_w=cpu_p,
            gpu_temp=gt,
            gpu_util=gu,
            gpu_freq_mhz=gf,
            gpu_power_w=gp,
            cpu_fan_rpm=fan_rpm,
            ram_util=mem_u,
            ram_temp=mem_t,
            ram_freq_mhz=mem_f,
            display_mode=cfg.display_mode_code,
            cycle_interval=cfg.cycle_interval,
            use_fahrenheit=cfg.use_fahrenheit,
            show_gpu=cfg.show_gpu,
        )
        print("\nGenerated 64-byte HID Packet:")
    hex_dump = " ".join(f"{b:02X}" for b in packet)
    print(f"  {hex_dump}")


def cmd_run(args):
    setup_logging(args.verbose)
    cfg = Config.load(args.config)

    # CLI flag overrides
    temp_unit = getattr(args, "temp_unit", None)
    if temp_unit:
        cfg.temp_unit = temp_unit

    display_mode = getattr(args, "display_mode", None)
    if display_mode:
        cfg.display_mode_str = display_mode

    daemon = OcypusDaemon(cfg)
    daemon.start()


def main():
    parser = argparse.ArgumentParser(
        prog="ocypus-ctl",
        description="Ocypus Digital Controller daemon and diagnostic tool for Linux & Proxmox 9",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("-c", "--config", help="Path to config file")

    subparsers = parser.add_subparsers(dest="command")

    # detect
    subparsers.add_parser("detect", help="Scan USB bus and Linux hwmon sensors")

    # status
    subparsers.add_parser("status", help="Show single reading and generated packet hex")

    # run
    p_run = subparsers.add_parser("run", help="Run controller in foreground")
    p_run.add_argument("--temp-unit", choices=["celsius", "fahrenheit"], help="Temperature unit")
    p_run.add_argument(
        "--display-mode",
        choices=["temp", "util", "cycle", "power", "watt", "ram"],
        help="Display mode (temp, util, cycle, watt/power, ram)",
    )

    # daemon
    p_daemon = subparsers.add_parser("daemon", help="Run controller in daemon mode")
    p_daemon.add_argument("--temp-unit", choices=["celsius", "fahrenheit"], help="Temperature unit")
    p_daemon.add_argument(
        "--display-mode",
        choices=["temp", "util", "cycle", "power", "watt", "ram"],
        help="Display mode (temp, util, cycle, watt/power, ram)",
    )

    args = parser.parse_args()

    if args.command == "detect":
        cmd_detect(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command in ("run", "daemon"):
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
