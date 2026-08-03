#!/usr/bin/env python3
"""
serial-boot-safe.py — Boot EVK with safe DTB via serial console.

Waits for U-Boot autoboot prompt, interrupts it, then selects
boot menu option 1 (USB SS v5) instead of default option 4 (Ortho-Bender).

Usage:
    python3 tools/serial-boot-safe.py [--option N] [--port /dev/ttyUSBx]
"""

import serial
import sys
import time

PORT = sys.argv[sys.argv.index('--port') + 1] if '--port' in sys.argv else '/dev/ttyUSB2'
BAUD = 115200
OPTION = sys.argv[sys.argv.index('--option') + 1] if '--option' in sys.argv else '1'
TIMEOUT = 120  # max seconds to wait for boot

ser = serial.Serial(PORT, BAUD, timeout=0.5)
buf = ""
phase = "waiting"  # waiting -> uboot -> menu -> booting -> done
start = time.time()

print(f"[boot] Listening on {PORT} @ {BAUD}. Power-cycle the board now.")
print(f"[boot] Will select boot option {OPTION}")
print(f"[boot] Timeout: {TIMEOUT}s")
print("=" * 60)

try:
    while time.time() - start < TIMEOUT:
        data = ser.read(1024)
        if not data:
            continue

        text = data.decode('utf-8', errors='replace')
        sys.stdout.write(text)
        sys.stdout.flush()
        buf += text

        # Keep buffer manageable
        if len(buf) > 8192:
            buf = buf[-4096:]

        # Phase: intercept autoboot
        if phase == "waiting" and "Hit any key to stop autoboot" in buf:
            print("\n[boot] >>> Intercepting autoboot!")
            ser.write(b' ')  # any key to stop
            time.sleep(0.3)
            phase = "uboot"
            buf = ""

        # Phase: at U-Boot prompt, run boot command
        if phase == "uboot" and ("=>" in buf or "u-boot=>" in buf.lower()):
            print(f"\n[boot] >>> At U-Boot prompt, running 'run bootcmd'")
            time.sleep(0.5)
            ser.write(b'run bootcmd\r\n')
            phase = "menu"
            buf = ""

        # Phase: select boot menu entry
        if phase == "menu" and "Enter choice:" in buf:
            print(f"\n[boot] >>> Selecting option {OPTION}")
            time.sleep(0.5)
            ser.write(f'{OPTION}\r\n'.encode())
            phase = "booting"
            buf = ""

        # Phase: kernel booting, wait for login prompt
        if phase == "booting" and ("login:" in buf or "root@" in buf):
            print(f"\n[boot] >>> Boot complete! Login prompt detected.")
            phase = "done"
            break

    if phase == "done":
        print("\n" + "=" * 60)
        print("[boot] SUCCESS — board booted with option", OPTION)
    elif phase == "booting":
        print("\n" + "=" * 60)
        print("[boot] Kernel is booting... (login prompt not yet seen)")
        print("[boot] Check SSH access: ssh root@192.168.77.2")
    else:
        print("\n" + "=" * 60)
        print(f"[boot] TIMEOUT after {TIMEOUT}s, phase: {phase}")

except KeyboardInterrupt:
    print("\n[boot] Interrupted by user")
finally:
    ser.close()
