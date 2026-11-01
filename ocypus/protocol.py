"""
Reverse-engineered protocol definitions for Ocypus & Hongtai digital display controllers.
Extracted from Ocypus Digital Elite 2.0.6 (Dongguan Hongtai Technology Co., Ltd.)
"""

import datetime
from typing import Optional, Dict, Any, List

# Standard USB HID Vendor and Product IDs
SUPPORTED_DEVICES = [
    {"vid": 0x5131, "pid": 0x2016, "name": "Ocypus Digital Display (Standard)"},
    {"vid": 0x1A2C, "pid": 0x434D, "usage_page": 0xFF01, "interface": 1, "name": "Ocypus Digital Display (YCC Custom)"},
    # Common Hongtai OEM family devices sharing the identical protocol
    {"vid": 0x5131, "pid": 0x2007, "name": "Hongtai Public Digital Display"},
    {"vid": 0x5131, "pid": 0x2008, "name": "YiCheng Digital Display"},
    {"vid": 0x5131, "pid": 0x2009, "name": "Alseye Digital Display"},
    {"vid": 0x5131, "pid": 0x200A, "name": "RuiTuo Digital Display"},
    {"vid": 0x5131, "pid": 0x200B, "name": "Cooling Digital Display"},
    {"vid": 0x5131, "pid": 0x200C, "name": "MSI Digital Display"},
    {"vid": 0x5131, "pid": 0x200D, "name": "CoolMai Digital Display"},
    {"vid": 0x5131, "pid": 0x200E, "name": "TT Segment LCD"},
    {"vid": 0x5131, "pid": 0x2017, "name": "Cooling 2024 Digital Display"},
    {"vid": 0x5131, "pid": 0x2018, "name": "SAMA Digital Display"},
    {"vid": 0x5131, "pid": 0x2019, "name": "1stPlayer Digital Display"},
    {"vid": 0x5131, "pid": 0x201A, "name": "YiChen TT Digital Display"},
]

DISPLAY_MODE_TEMP = 0
DISPLAY_MODE_UTIL = 1
DISPLAY_MODE_CYCLE = 2
DISPLAY_MODE_RAM = 2  # on MSI/RAM models


def clamp(val: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(val, max_val))


def split_float(val: float, max_int: int = 999) -> tuple[int, int]:
    """Splits a float into integer part and 2-decimal fractional part (0..99)."""
    val = max(0.0, min(float(val), float(max_int)))
    integer_part = int(val)
    frac_part = int(round((val - integer_part) * 100))
    return integer_part, min(99, max(0, frac_part))


def split_bcd_digits(val: int) -> list[int]:
    """Splits integer (0..999) into 3 BCD digits [hundreds, tens, ones]."""
    val = max(0, min(999, int(val)))
    hundreds = val // 100
    tens = (val // 10) % 10
    ones = val % 10
    return [hundreds, tens, ones]


class OcypusPacketBuilder:
    @staticmethod
    def build_standard_packet(
        cpu_temp: float = 0.0,
        cpu_util: float = 0.0,
        cpu_freq_mhz: float = 0.0,
        cpu_power_w: float = 0.0,
        cpu_voltage_v: float = 0.0,
        gpu_temp: float = 0.0,
        gpu_util: float = 0.0,
        gpu_freq_mhz: float = 0.0,
        gpu_power_w: float = 0.0,
        cpu_fan_rpm: int = 0,
        chassis_fan_rpm: int = 0,
        ram_util: float = 0.0,
        ram_temp: float = 0.0,
        ram_freq_mhz: float = 0.0,
        display_mode: int = DISPLAY_MODE_TEMP,
        cycle_interval: int = 5,
        use_fahrenheit: bool = False,
        show_gpu: bool = False,
        now: Optional[datetime.datetime] = None,
    ) -> bytes:
        """
        Builds the 64-byte HID report for Ocypus Digital / Hongtai controllers.
        """
        if now is None:
            now = datetime.datetime.now()

        # Handle temperature conversion if Fahrenheit requested
        temp_unit = 1 if use_fahrenheit else 0
        if use_fahrenheit:
            cpu_temp_display = (9.0 / 5.0) * cpu_temp + 32.0
            gpu_temp_display = (9.0 / 5.0) * gpu_temp + 32.0
            ram_temp_display = (9.0 / 5.0) * ram_temp + 32.0
        else:
            cpu_temp_display = cpu_temp
            gpu_temp_display = gpu_temp
            ram_temp_display = ram_temp

        cpu_temp_int, cpu_temp_dec = split_float(cpu_temp_display, max_int=999)
        gpu_temp_int, gpu_temp_dec = split_float(gpu_temp_display, max_int=999)
        ram_temp_int, ram_temp_dec = split_float(ram_temp_display, max_int=999)

        cpu_util_int, cpu_util_dec = split_float(cpu_util, max_int=100)
        gpu_util_int, gpu_util_dec = split_float(gpu_util, max_int=100)
        ram_util_int, ram_util_dec = split_float(ram_util, max_int=100)

        # Power draw: split into hundreds digit, and mod 100
        cpu_power_int = int(clamp(cpu_power_w, 0, 9999))
        cpu_power_extra = cpu_power_int // 100
        cpu_power_start = cpu_power_int % 100
        cpu_power_end = int(round((cpu_power_w - cpu_power_int) * 100)) % 100

        gpu_power_int = int(clamp(gpu_power_w, 0, 9999))
        gpu_power_extra = gpu_power_int // 100
        gpu_power_start = gpu_power_int % 100
        gpu_power_end = int(round((gpu_power_w - gpu_power_int) * 100)) % 100

        # Frequency: split into hundreds (div 100) and mod 100
        cpu_freq_int = int(clamp(cpu_freq_mhz, 0, 9999))
        cpu_freq_start = cpu_freq_int // 100
        cpu_freq_end = cpu_freq_int % 100

        gpu_freq_int = int(clamp(gpu_freq_mhz, 0, 9999))
        gpu_freq_start = gpu_freq_int // 100
        gpu_freq_end = gpu_freq_int % 100

        ram_freq_int = int(clamp(ram_freq_mhz, 0, 9999))
        ram_freq_start = ram_freq_int // 100
        ram_freq_end = ram_freq_int % 100

        # Voltage
        cpu_vid_int, cpu_vid_dec = split_float(cpu_voltage_v, max_int=99)

        # Fan RPM: split into /100 and %100
        cpu_fan_rpm = int(clamp(cpu_fan_rpm, 0, 9999))
        cpu_fan_start = cpu_fan_rpm // 100
        cpu_fan_end = cpu_fan_rpm % 100

        chassis_fan_rpm = int(clamp(chassis_fan_rpm, 0, 9999))
        chassis_fan_start = chassis_fan_rpm // 100
        chassis_fan_end = chassis_fan_rpm % 100

        # Date & Time
        year_str = f"{now.year:04d}"
        year_star = int(year_str[:2])  # Century, e.g. 20
        year_end = int(year_str[2:])   # Year within century, e.g. 26
        month = now.month
        day_of_month = now.day
        hours = now.hour
        minutes = now.minute
        seconds = now.second
        # Sunday is 0 in device protocol, python weekday() has Monday as 0 -> adjust:
        day_of_week = (now.weekday() + 1) % 7

        cpu_flag = 1 if show_gpu else 0

        # DarkFlash selector bitmask: 1=CPU temp, 2=CPU util, 4=GPU temp, 8=GPU util
        dark_flash = 1

        packet = bytearray(64)
        packet[0] = 0x01
        packet[1] = 0x00
        packet[2] = 0x01
        packet[3] = 0x02
        packet[4] = cpu_temp_int & 0xFF
        packet[5] = cpu_temp_dec & 0xFF
        packet[6] = temp_unit & 0xFF
        packet[7] = cpu_util_int & 0xFF
        packet[8] = cpu_power_start & 0xFF
        packet[9] = cpu_power_end & 0xFF
        packet[10] = cpu_freq_start & 0xFF
        packet[11] = cpu_freq_end & 0xFF
        packet[12] = cpu_vid_int & 0xFF
        packet[13] = cpu_vid_dec & 0xFF
        packet[14] = gpu_temp_int & 0xFF
        packet[15] = gpu_temp_dec & 0xFF
        packet[16] = temp_unit & 0xFF
        packet[17] = gpu_util_int & 0xFF
        packet[18] = gpu_power_start & 0xFF
        packet[19] = gpu_power_end & 0xFF
        packet[20] = gpu_freq_start & 0xFF
        packet[21] = gpu_freq_end & 0xFF
        packet[22] = cpu_fan_start & 0xFF
        packet[23] = cpu_fan_end & 0xFF
        packet[24] = chassis_fan_start & 0xFF
        packet[25] = chassis_fan_end & 0xFF
        packet[26] = year_star & 0xFF
        packet[27] = year_end & 0xFF
        packet[28] = month & 0xFF
        packet[29] = day_of_month & 0xFF
        packet[30] = hours & 0xFF
        packet[31] = minutes & 0xFF
        packet[32] = seconds & 0xFF
        packet[33] = day_of_week & 0xFF
        packet[34] = ram_util_int & 0xFF
        packet[35] = cpu_power_extra & 0xFF
        packet[36] = gpu_power_extra & 0xFF
        packet[37] = display_mode & 0xFF
        packet[38] = cycle_interval & 0xFF
        packet[39] = cpu_flag & 0xFF
        packet[40] = dark_flash & 0xFF
        packet[41] = display_mode & 0xFF
        packet[42] = display_mode & 0xFF
        packet[43] = ram_temp_int & 0xFF
        packet[44] = ram_temp_dec & 0xFF
        packet[45] = temp_unit & 0xFF
        packet[46] = ram_freq_start & 0xFF
        packet[47] = ram_freq_end & 0xFF
        packet[48] = display_mode & 0xFF
        packet[49] = cpu_util_dec & 0xFF
        packet[50] = gpu_util_dec & 0xFF
        packet[51] = ram_util_dec & 0xFF
        # Bytes 52..63 are 0x00

        return bytes(packet)

    @staticmethod
    def build_ycc_packet(
        val: float = 0.0,
        show_gpu: bool = False,
        use_fahrenheit: bool = False,
        is_temp: bool = True,
        byte1: int = 0xFF,
        byte2: int = 0xFF,
    ) -> bytes:
        """
        Builds the report for Ocypus YCC Custom device (0x1A2C:0x434D).
        Report Descriptor defines Report ID 0x07 with Report Count 63 (64 bytes total).
        Packet format: [0x07, byte1, byte2, hundreds, tens, ones, ... 58 zero bytes ...]
        """
        if is_temp and use_fahrenheit:
            val = (9.0 / 5.0) * val + 32.0
        digits = split_bcd_digits(int(round(val)))
        data = bytearray([0x07, byte1 & 0xFF, byte2 & 0xFF])
        data.extend(digits)
        if len(data) < 64:
            data.extend([0x00] * (64 - len(data)))
        return bytes(data)
