# Boot Hang Analysis — Ortho-Bender DTB Galcore Freeze

**Date**: 2026-04-17
**Author**: Isaac Park
**Status**: Fixed — wifi.dtsi `<&hsio_blk_ctrl>` removed

## Symptom

Board option 4 (Ortho-Bender DTB) freezes at Galcore GPU driver init
(~1.83 seconds into kernel boot). Last visible kernel message:

```
[    1.824115] Galcore version 6.4.3.p4.398061
```

No further output. Board is completely unresponsive — serial console,
SSH, and all network interfaces are unreachable.

Safe DTB (option 1, `imx8mp-evk-usb-ss-v5.dtb`) boots normally
through the same kernel and rootfs in ~16 seconds with full WiFi,
AP mode, and FastAPI backend operational.

## Root Cause

**SoC DTSI version mismatch between Ortho-Bender DTB and the running kernel.**

The Ortho-Bender DTS includes `imx8mp-evk.dts` from the NXP linux-imx
kernel tree used during the Yocto build. This base DTS pulls in a
**legacy** version of the SoC DTSI (`imx8mp.dtsi`) that uses the old
HSIO BLK_CTRL model for PCIe and USB3 subsystems.

However, the kernel image on the board was built from a **newer/patched**
version that uses the upstream PHY subsystem model.

### Key Differences (decompiled DTB comparison)

| Component | Ortho-Bender DTB (broken) | V5 DTB (working) |
|-----------|--------------------------|-------------------|
| PCIe PHY clock | `<&hsio_blk_ctrl>` (ref) | `<&clk 0>` (CCM phy) |
| PCIe PHY properties | resets, power-domains, fsl,refclk-pad-mode | ext_osc, simple clock |
| PCIe controller compatible | `fsl,imx8mp-pcie` only | `fsl,imx8mp-pcie` + `snps,dw-pcie` |
| PCIe resets | 2 (apps, turnoff) | 5 (pciephy, pciephy_perst, apps, clkreq, turnoff) |
| PCIe power-domains | hsio_blk_ctrl index 3 | Separate pm-domain (pcie) |

### Why Galcore Hangs (not just PCIe)

The HSIO BLK_CTRL (`blk-ctrl@32f10000`) manages shared bus clocks
and power sequencing for the HSIO domain. When the kernel tries to
parse the legacy PCIe PHY clock reference `<&hsio_blk_ctrl>`, it fails
because the node lacks `#clock-cells`:

```
OF: /soc@0/bus@32c00000/pcie-phy@32f00000: could not get #clock-cells
    for /soc@0/bus@32c00000/blk-ctrl@32f10000
```

This failure corrupts the HSIO power domain initialization sequence,
which cascades to the GPU (Galcore) since both share bus-level
clock gating in the SoC.

## Verification Steps

| Test | DTB Used | Result |
|------|----------|--------|
| 1. Boot option 1 (safe) | imx8mp-evk-usb-ss-v5.dtb | PASS — full boot |
| 2. Boot option 4 (ortho-bender) | imx8mp-ortho-bender.dtb | FAIL — Galcore hang |
| 3. OB DTB with PCIe disabled | fdtput status=disabled on pcie+pcie_phy | FAIL — still hangs |
| 4. V5 DTB with model name only | V5 base + model="Ortho-Bender..." | PASS — full boot |

Test 3 proves the issue is not just the PCIe driver probe but
the overall SoC DTSI incompatibility. Test 4 confirms the V5
base DTB is fully compatible with the running kernel.

## Fix Strategy

Rebuild `imx8mp-ortho-bender.dtb` using the V5-compatible SoC DTSI
as the base. Two approaches:

### Option A: DTS Source Fix (Yocto build, recommended for production)

Update `imx8mp-ortho-bender.dts` to `#include` the corrected
`imx8mp-evk.dts` from the same kernel source tree that produced
the V5 DTB. This requires identifying which kernel tree/commit
the production image was built from.

### Option B: Binary DTB Patch (immediate, for development)

Use `fdtput` to apply Ortho-Bender customizations directly onto
the V5 DTB:

1. Copy `imx8mp-evk-usb-ss-v5.dtb` as base
2. Add M7 reserved-memory regions
3. Add GPIO hogs for motor pins
4. Add ECSPI2 motor configuration
5. Disable unused peripherals (ov5640, bridges)
6. Set model name

This is the current approach for development boards.

## FT4232H Board Recovery

When the board hangs, recovery requires hardware reset via the
FT4232H JTAG adapter connected to the EVK:

### Pin Mapping (from OpenOCD `imx8mp-evk.cfg`)

| Signal | ADBUS Pin | Bit | Function |
|--------|-----------|-----|----------|
| RESET_B | ADBUS4 | 0x10 | SoC reset |
| nSRST | ADBUS5 | 0x20 | System reset (SYS_nRST) |
| IO_nRST | ADBUS6 | 0x40 | I/O reset |
| ONOFF_B | ADBUS7 | 0x80 | Power on/off toggle |

### Reset Command (pyftdi)

```python
from pyftdi.gpio import GpioMpsseController

nSRST = 0x20
ONOFF_B = 0x80

gpio = GpioMpsseController()
gpio.configure('ftdi://ftdi:4232:1:4/1',
               direction=(nSRST | ONOFF_B), frequency=1e6)
gpio.write(nSRST | ONOFF_B)   # both high (inactive)
time.sleep(0.1)
gpio.write(ONOFF_B)            # nSRST low (assert reset)
time.sleep(0.2)
gpio.write(nSRST | ONOFF_B)   # release
gpio.close()
```

### Combined Reset + Serial Boot Script

See `tools/serial-boot-safe.py` for automated U-Boot intercept
and safe boot option selection.

## U-Boot Configuration

- **bootdelay**: Changed from 5 to 3 seconds (`setenv bootdelay 3; saveenv`)
- **extlinux.conf TIMEOUT**: 100 (= 10 seconds, 1/10s units)
- **Default boot**: `emmc-ortho-bender` (option 4)
- **Safe boot**: Option 1 (`emmc-usb-ss-v5`)

## Fix Applied

**Commit**: `imx8mp-ortho-bender-wifi.dtsi` — removed legacy `<&hsio_blk_ctrl>`
clock reference from `&pcie_phy` node.

Before (broken):
```dts
&pcie_phy {
    fsl,refclk-pad-mode = <IMX8_PCIE_REFCLK_PAD_INPUT>;
    fsl,clkreq-unsupported;
    clocks = <&hsio_blk_ctrl>;   /* ← causes Galcore hang */
    clock-names = "ref";
    status = "okay";
};
```

After (fixed):
```dts
&pcie_phy {
    ext_osc = <1>;
    status = "okay";
};
```

The SoC DTSI (included via `imx8mp-evk.dts`) provides the correct PCIe
PHY clock from the CCM. The overlay must not override it with a legacy
HSIO BLK_CTRL reference.

**Yocto build note**: The fix requires that the kernel source tree used
by the Yocto build (`linux-imx` recipe) contains the V5-compatible SoC
DTSI (`fsl,imx8mp-hsio-mix` model, not `fsl,imx8mp-hsio-blk-ctrl`).
Verify with `dtc -I dtb -O dts` after rebuild.

## Related Files

| File | Role |
|------|------|
| `meta-ortho-bender/recipes-bsp/linux/linux-imx/dts/imx8mp-ortho-bender.dts` | Main DTS |
| `meta-ortho-bender/recipes-bsp/linux/linux-imx/dts/imx8mp-ortho-bender-wifi.dtsi` | WiFi/PCIe overlay (legacy model) |
| `meta-ortho-bender/recipes-bsp/linux/linux-imx/dts/imx8mp-ortho-bender-m7.dtsi` | M7 remoteproc |
| `meta-ortho-bender/recipes-bsp/linux/linux-imx/dts/imx8mp-ortho-bender-motors.dtsi` | Motor GPIO hogs |
| `tools/serial-boot-safe.py` | Serial console boot recovery |
| `/usr/share/openocd/scripts/interface/ftdi/imx8mp-evk.cfg` | FT4232H pin mapping reference |
