# i.MX8MP EVK Camera Bring-up Guide

## Overview

This document covers OV5640 MIPI CSI camera bring-up on the NXP i.MX8MP-EVK
base board (SPF-46370 B1) using the NXP MINISASTOCSI camera adapter (SCH-29853 A1).

## Hardware

### EVK Connector Mapping

| Connector | Function | I2C Bus | MIPI Controller |
|-----------|----------|---------|-----------------|
| J12 | CSI1 (Camera 1#) | I2C2 (bus 1, 0x30a30000) | csi@32e40000 |
| J13 | CSI2 (Camera 2#) | I2C3 (bus 2, 0x30a40000) | csi@32e50000 |
| J14 | MIPI DSI (Display) | — | — |
| J15 | LVDS0 | — | — |
| J16 | LVDS1 | — | — |

> **Note:** Verified from BB schematic SPF-46370_B1 page 12 (Camera CSI)
> and page 13 (DSI Display). Previous mapping had J14/J12/J13 wrong.

### Camera Adapter Board (MINISASTOCSI)

The adapter board converts the mini-SAS connector to a 40-pin FPC for the
OV5640 camera module.

**Power:**
- AVDD (2.8V): On-board regulator (XC6222B) from 3.3V
- DOVDD (1.8V): Passthrough from base board VDD_1V8
- DVDD (1.5V): OV5640 internal regulator (U2 DNP)
- MCLK (24MHz): From SoC CCM_CLKO2 via mini-SAS (Y1 oscillator DNP)

### Shared GPIO (EVK Hardware Limitation)

**IMPORTANT:** Camera 1# (J12) and Camera 2# (J13) share the same power-down
and reset GPIO pins on the EVK base board:

| Signal | GPIO | Phandle | Pin | Flags |
|--------|------|---------|-----|-------|
| PWDN | GPIO2_IO11 | 0x38 | 11 | 0 (active-high) |
| RESET | GPIO1_IO06 | 0x31 | 6 | 1 (active-low) |

This means:
- Only one camera can be active at a time
- The CSI2 DT node must use the same GPIO pins as CSI1
- The default CSI2 DT node uses GPIO4_IO01/IO00 which are WRONG

### Stock DTB PWDN GPIO Bug

The stock NXP DTB (`imx8mp-evk.dtb`) has a mismatch in the CSI1 OV5640 node:
- `powerdown-gpios` property: **GPIO2_IO11** (phandle 0x38, pin 11)
- `pinctrl csi0_pwn_grp`: SAI2_MCLK pad muxed as **GPIO4_IO27** (ALT5)

These are different physical pads. The driver toggles GPIO2_IO11 but the
actual PWDN hardware path goes through GPIO4_IO27. Fix:

```
fdt set /soc@0/bus@30800000/i2c@30a30000/ov5640_mipi@3c powerdown-gpios <0x3b 0x1b 0x00>
```

GPIO phandle map (stock DTB): GPIO1=0x31, GPIO2=0x38, GPIO3=0xa4, GPIO4=0x3b, GPIO5=0x25

Reference: [NXP KB - OV5640 support on imx8mp](https://community.nxp.com/t5/i-MX-Processors-Knowledge-Base/ov5640-support-on-imx8mp/ta-p/1305725)

## Device Tree Configuration

### CSI1 (Default, camera on J12)

Use the stock `imx8mp-evk.dtb` with PWDN GPIO fix (see above).

### CSI2 (Camera on J13)

The CSI2 OV5640 node requires DTB modification. The following U-Boot `fdt`
commands fix the GPIO definitions and enable the CSI2 pipeline:

```bash
# Load kernel and DTB
load mmc 2:1 0x40480000 Image-medit-6.1
load mmc 2:1 0x43000000 imx8mp-evk-medit.dtb

# Setup FDT
fdt addr 0x43000000
fdt resize 8192

# Disable CSI1 OV5640 (not connected)
fdt set /soc@0/bus@30800000/i2c@30a30000/ov5640_mipi@3c status disabled

# Enable CSI2 OV5640
fdt set /soc@0/bus@30800000/i2c@30a40000/ov5640_mipi@3c status okay

# Enable CSI2 MIPI controller
fdt set /soc@0/bus@32c00000/camera/csi@32e50000 status okay

# FIX: Change PWDN from GPIO4_IO01 to GPIO2_IO11 (shared pin)
# Format: [phandle(4B) pin(4B) flags(4B)]
fdt set /soc@0/bus@30800000/i2c@30a40000/ov5640_mipi@3c \
    powerdown-gpios [00 00 00 38 00 00 00 0b 00 00 00 00]

# FIX: Change RESET from GPIO4_IO00 to GPIO1_IO06 (shared pin)
fdt set /soc@0/bus@30800000/i2c@30a40000/ov5640_mipi@3c \
    reset-gpios [00 00 00 31 00 00 00 06 00 00 00 01]

# Set boot args and boot
setenv bootargs console=ttymxc1,115200 root=/dev/mmcblk1p2 rootwait rw \
    ip=192.168.77.2::192.168.77.1:255.255.255.0:imx8mp-quarkers-evk:eth0:off
booti 0x40480000 - 0x43000000
```

## Automated Boot Script

`tools/evk-csi2-ov5640-boot.py` automates the U-Boot DTB modification:

```bash
python3 tools/evk-csi2-ov5640-boot.py
```

Requires: `pyserial` (`pip install pyserial`)

## Camera Test Script

`tools/evk-camera-test.sh` runs on the EVK to capture images:

```bash
# On EVK via SSH
./evk-camera-test.sh              # auto-detect and capture
./evk-camera-test.sh --list       # list devices only
./evk-camera-test.sh --stream 5   # stream for 5 seconds
```

## Troubleshooting

### OV5640 I2C timeout (error -110)

```
ov5640 2-003c: ov5640_read_reg: error: reg=300a
ov5640 2-003c: ov5640_check_chip_id: failed to read chip identifier
```

**Check in order:**

1. **Physical connection**: Camera module FPC seated in adapter P1 connector?
2. **Mini-SAS cable**: Firmly connected to J12 (CSI1) or J13 (CSI2)?
3. **Correct I2C bus**: Camera on J12 = bus 1 (I2C2), Camera on J13 = bus 2 (I2C3)
4. **PWDN GPIO**: CSI1 must use GPIO4_IO27 (fix stock DTB bug, see above)
5. **GPIO pins**: CSI2 node MUST use GPIO2_IO11/GPIO1_IO06 (not GPIO4)
6. **MCLK**: Check `cat /sys/kernel/debug/clk/ipp_do_clko2/clk_enable_count`
7. **U-Boot bare-metal test**: `i2c dev 1; i2c probe` — if 0x3c missing, HW fault
8. **Camera module**: Try a known-good OV5640 module

### Dummy regulators warning

```
ov5640 2-003c: supply DOVDD not found, using dummy regulator
```

This is normal on the EVK. The camera adapter board has always-on power rails
(2.8V from 3.3V regulator, 1.8V passthrough). No DT regulator definitions needed.

## Reference Documents

| Document | Location |
|----------|----------|
| EVK Base Board schematic | `i.mx8mp_ws/ref_data/8MPLUS-BB/SPF-46370_B1.pdf` |
| Camera adapter schematic | `i.mx8mp_ws/ref_data/MINISASTOCSI/MINISASTOCSI/SPF-29853_A1.pdf` |
| CPU Board schematic | `i.mx8mp_ws/ref_data/8MPLUSLPD4-CPU/SPF-46368_A3.pdf` |
| Camera Sensor Porting Guide | `i.mx8mp_ws/ref_data/IMX8MPCSPUG.pdf` |
