#!/usr/bin/env python3
"""
evk-csi2-ov5640-boot.py — Boot i.MX8MP EVK with CSI2 OV5640 GPIO fix

Connector mapping: J12=CSI1(I2C2), J13=CSI2(I2C3), J14=DSI(Display)

Problem: CSI2 OV5640 DT node uses GPIO4_IO01/IO00 for PWDN/RESET,
but EVK HW shares PWDN/RESET between CSI1 and CSI2:
  - PWDN:  GPIO2_IO11 (phandle 0x38, pin 11, active-high)
  - RESET: GPIO1_IO06 (phandle 0x31, pin 6,  active-low)

Note: Stock DTB also has CSI1 PWDN bug — pinctrl muxes GPIO4_IO27 but
powerdown-gpios references GPIO2_IO11. Fix with: <0x3b 0x1b 0x00>

This script:
1. Reboots EVK via serial (reboot -f)
2. Interrupts U-Boot
3. Loads quarkers kernel + DTB from eMMC
4. Fixes CSI2 OV5640 GPIO phandles via fdt commands
5. Boots Linux

Reference: https://community.nxp.com/t5/i-MX-Processors-Knowledge-Base/
           ov5640-support-on-imx8mp/ta-p/1305725
"""

import serial
import time
import sys
import subprocess

SERIAL_PORT = "/dev/ttyUSB2"
BAUD_RATE = 115200
TIMEOUT = 1

# U-Boot commands for DTB modification
UBOOT_COMMANDS = [
    # Load Medit kernel from eMMC partition 1
    ("load mmc 2:1 0x40480000 Image-medit-6.1", 5),
    # Load Medit DTB from eMMC partition 1
    ("load mmc 2:1 0x43000000 imx8mp-evk-medit.dtb", 3),
    # Setup FDT
    ("fdt addr 0x43000000", 1),
    ("fdt resize 8192", 1),
    # Disable CSI1 OV5640 (camera not on J12)
    ("fdt set /soc@0/bus@30800000/i2c@30a30000/ov5640_mipi@3c status disabled", 1),
    # Enable CSI2 OV5640 (camera on J13)
    ("fdt set /soc@0/bus@30800000/i2c@30a40000/ov5640_mipi@3c status okay", 1),
    # Enable CSI2 MIPI controller
    ("fdt set /soc@0/bus@32c00000/camera/csi@32e50000 status okay", 1),
    # FIX: Change CSI2 OV5640 PWDN from GPIO4_IO01 to GPIO2_IO11 (shared pin)
    # Format: <phandle(u32) pin(u32) flags(u32)> in hex
    # GPIO2 phandle=0x38, pin=11(0x0b), flags=0 (active-high)
    ("fdt set /soc@0/bus@30800000/i2c@30a40000/ov5640_mipi@3c powerdown-gpios <0x38 0x0b 0x00>", 1),
    # FIX: Change CSI2 OV5640 RESET from GPIO4_IO00 to GPIO1_IO06 (shared pin)
    # GPIO1 phandle=0x31, pin=6(0x06), flags=1 (active-low)
    ("fdt set /soc@0/bus@30800000/i2c@30a40000/ov5640_mipi@3c reset-gpios <0x31 0x06 0x01>", 1),
    # Verify changes
    ("fdt print /soc@0/bus@30800000/i2c@30a40000/ov5640_mipi@3c powerdown-gpios", 1),
    ("fdt print /soc@0/bus@30800000/i2c@30a40000/ov5640_mipi@3c reset-gpios", 1),
    ("fdt print /soc@0/bus@30800000/i2c@30a40000/ov5640_mipi@3c status", 1),
    # Set boot args
    ("setenv bootargs console=ttymxc1,115200 root=/dev/mmcblk1p2 rootwait rw "
     "ip=192.168.77.2::192.168.77.1:255.255.255.0:imx8mp-quarkers-evk:eth0:off", 1),
    # Boot
    ("booti 0x40480000 - 0x43000000", 0),
]


def send_cmd(ser, cmd, wait=1):
    """Send command to serial and wait for response."""
    ser.write((cmd + "\r\n").encode())
    ser.flush()
    time.sleep(wait)
    resp = ser.read(ser.in_waiting or 1024).decode(errors="replace")
    return resp


def wait_for(ser, pattern, timeout=60):
    """Wait for a pattern in serial output."""
    buf = ""
    start = time.time()
    while time.time() - start < timeout:
        data = ser.read(ser.in_waiting or 1)
        if data:
            text = data.decode(errors="replace")
            buf += text
            sys.stdout.write(text)
            sys.stdout.flush()
            if pattern in buf:
                return True, buf
        else:
            time.sleep(0.1)
    return False, buf


def main():
    print("=== EVK CSI2 OV5640 Boot with GPIO Fix ===\n")

    # Step 1: Reboot EVK via serial
    print("[1/4] Rebooting EVK via serial...")
    try:
        reboot_ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        reboot_ser.write(b"\r\nroot\r\n")
        time.sleep(2)
        reboot_ser.write(b"reboot -f\r\n")
        time.sleep(1)
        reboot_ser.close()
    except Exception:
        pass
    print("  Reboot command sent")
    time.sleep(2)

    # Step 2: Open serial and wait for U-Boot
    print("[2/4] Opening serial port and waiting for U-Boot...")
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=TIMEOUT)
    ser.reset_input_buffer()

    # Spam Enter/Space to interrupt U-Boot autoboot
    print("  Sending interrupt keys...")
    for _ in range(30):
        ser.write(b"\r\n")
        time.sleep(0.2)
        data = ser.read(ser.in_waiting or 1)
        text = data.decode(errors="replace") if data else ""
        if "u-boot=>" in text or "Hit any key" in text:
            break

    # Wait for U-Boot prompt
    found, buf = wait_for(ser, "u-boot=>", timeout=30)
    if not found:
        print("\n  ERROR: U-Boot prompt not found. Check serial connection.")
        ser.close()
        sys.exit(1)
    print("\n  U-Boot prompt detected!")

    # Step 3: Execute DTB modification commands
    print("\n[3/4] Modifying DTB...")
    for cmd, wait in UBOOT_COMMANDS:
        short_desc = cmd[:70] + "..." if len(cmd) > 70 else cmd
        print(f"  > {short_desc}")
        resp = send_cmd(ser, cmd, wait)
        # Print response for verification commands
        if "fdt print" in cmd:
            for line in resp.split("\n"):
                line = line.strip()
                if line and "u-boot=>" not in line and cmd not in line:
                    print(f"    {line}")

    # Step 4: Wait for Linux boot
    print("\n[4/4] Booting Linux...")
    found, buf = wait_for(ser, "login:", timeout=120)
    if found:
        print("\n\n=== Boot complete! ===")
    else:
        print("\n\n  WARNING: Login prompt not detected within timeout")
        print("  Check serial output manually")

    ser.close()
    print("\nDone. Check camera with: ssh root@192.168.77.2 'dmesg | grep ov5640'")


if __name__ == "__main__":
    main()
