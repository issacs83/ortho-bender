#!/usr/bin/env python3
"""board-snapshot-worker.py — Capture board state via SSH (paramiko)."""

import paramiko
import sys
from datetime import datetime

BOARD_IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.77.2"

SECTIONS = [
    ("SYSTEM", [
        ("hostname", "hostname"),
        ("kernel", "uname -a"),
        ("uptime", "uptime"),
        ("date", "date"),
        ("rtc", "hwclock -r 2>/dev/null || echo 'NO RTC'"),
    ]),
    ("SERVICES", [
        ("enabled", "systemctl list-unit-files --state=enabled --no-pager"),
        ("running", "systemctl list-units --type=service --state=running --no-pager"),
        ("failed", "systemctl --failed --no-pager"),
        ("sdk-status", "systemctl status ortho-bender-sdk.service --no-pager 2>&1 || true"),
        ("ap-status", "systemctl status ortho-bender-ap.service --no-pager 2>&1 || true"),
    ]),
    ("NETWORK", [
        ("interfaces", "ifconfig -a 2>/dev/null"),
        ("routes", "route -n 2>/dev/null || echo 'route not available'"),
        ("dns", "cat /etc/resolv.conf 2>/dev/null"),
        ("eth0-network", "cat /etc/systemd/network/10-eth0.network 2>/dev/null || echo NONE"),
        ("mlan0-network", "cat /etc/systemd/network/20-mlan0-dhcp.network 2>/dev/null || echo NONE"),
        ("wpa-conf", "cat /etc/wpa_supplicant/wpa_supplicant-mlan0.conf 2>/dev/null || echo NONE"),
        ("hostapd-conf", "cat /etc/hostapd/ortho-bender-ap.conf 2>/dev/null || echo NONE"),
        ("udhcpd-conf", "cat /etc/udhcpd-uap0.conf 2>/dev/null || echo NONE"),
    ]),
    ("STORAGE", [
        ("disk-usage", "df -h"),
        ("mounts", "mount | grep -E 'mmcblk|ext4|vfat'"),
        ("boot-partition", "ls -la /run/media/boot-mmcblk2p1/ 2>/dev/null || echo 'not mounted'"),
        ("extlinux", "cat /run/media/boot-mmcblk2p1/extlinux/extlinux.conf 2>/dev/null || echo NONE"),
    ]),
    ("FIRMWARE", [
        ("remoteproc-state", "cat /sys/class/remoteproc/remoteproc0/state 2>/dev/null || echo NONE"),
        ("remoteproc-fw", "cat /sys/class/remoteproc/remoteproc0/firmware 2>/dev/null || echo NONE"),
        ("m7-firmware", "ls -la /lib/firmware/ortho* 2>/dev/null || echo NONE"),
    ]),
    ("APPLICATION", [
        ("opt-tree", "find /opt/ortho-bender -maxdepth 3 -type f 2>/dev/null | head -40 || echo NONE"),
        ("fastapi-health", "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/docs 2>/dev/null || echo DOWN"),
        ("python-version", "python3 --version 2>&1"),
        ("backend-log-tail", "tail -20 /var/log/ortho-backend.log 2>/dev/null || echo 'no log'"),
    ]),
    ("SECURITY", [
        ("ssh-config", "cat /etc/default/dropbear 2>/dev/null || echo NONE"),
        ("root-shell", "grep ^root /etc/passwd"),
        ("open-ports", "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null || echo 'no ss/netstat'"),
    ]),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_IP, username="root", password="ortho-bender", timeout=10)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"# Ortho-Bender Board Snapshot")
    print(f"# Board: {BOARD_IP}")
    print(f"# Captured: {now}")
    print(f"# {'=' * 68}")

    for section_name, commands in SECTIONS:
        print(f"\n{'#' * 72}")
        print(f"# {section_name}")
        print(f"{'#' * 72}\n")
        for label, cmd in commands:
            print(f"--- {label} ---")
            _stdin, stdout, stderr = c.exec_command(cmd)
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            print(out if out else err if err else "(empty)")
            print()

    c.close()


if __name__ == "__main__":
    main()
