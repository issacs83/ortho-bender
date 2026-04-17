#!/bin/sh
# fix-boot-delay.sh — Remove kernel ip= parameter from U-Boot env
# Run once on the board (via serial console or SSH) after flashing.
#
# Problem: kernel ip= parameter blocks boot ~100s waiting for eth0 link-up.
# Solution: Remove ip= from mmcargs; eth0 IP handled by systemd-networkd.
#
# Usage:
#   1. Enter U-Boot prompt (press SPACE during boot)
#   2. Run these commands:
#
#        printenv mmcargs
#        setenv mmcargs 'console=ttymxc1,115200 root=/dev/mmcblk2p2 rootwait rw'
#        saveenv
#        boot
#
#   Or from Linux userspace (fw_setenv must be installed):

set -e

if ! command -v fw_printenv >/dev/null 2>&1; then
    echo "ERROR: fw_setenv not found. Run from U-Boot prompt instead."
    echo ""
    echo "  U-Boot> setenv mmcargs 'console=ttymxc1,115200 root=/dev/mmcblk2p2 rootwait rw'"
    echo "  U-Boot> saveenv"
    exit 1
fi

echo "=== Current mmcargs ==="
fw_printenv mmcargs || true

echo ""
echo "=== Removing ip= parameter ==="
fw_setenv mmcargs 'console=ttymxc1,115200 root=/dev/mmcblk2p2 rootwait rw'

echo ""
echo "=== Updated mmcargs ==="
fw_printenv mmcargs

echo ""
echo "Done. Reboot to apply."
