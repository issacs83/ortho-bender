# CLAUDE.md -- Ortho-Bender Wire Bending Machine

## Project Summary
Orthodontic wire bending machine using NXP i.MX8MP SoC. Converts 3D treatment
plans into precisely bent wires for dental orthodontic patients.

## Quick Reference

### Build Commands
```bash
# Full Yocto image (development)
KAS_BUILD_DIR=build-ortho-bender kas shell kas/base.yml:kas/ortho-bender-dev.yml -c "bitbake ortho-bender-image-dev"

# M7 firmware only
cmake -B build-firmware -S src/firmware -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake
cmake --build build-firmware

# A53 application (host build for testing)
cmake -B build-app -S src/app
cmake --build build-app

# Unit tests
cd tests && cmake -B build && cmake --build build && ctest --output-on-failure

# Flash to device
sudo uuu -b emmc_all imx-boot ortho-bender-image-dev.wic
```

### Architecture
```
┌──────────────────────────────────────────────────────────┐
│                       i.MX8MP SoC                        │
│                                                          │
│  ┌──────────────────────────┐  ┌───────────────────────┐ │
│  │  Cortex-A53 x4 (Linux)   │  │  Cortex-M7 (FreeRTOS) │ │
│  │                          │  │                       │ │
│  │  ┌──────────┐ ┌────────┐│  │ ┌───────────────────┐ │ │
│  │  │ Qt6 GUI  │ │ PatDB  ││  │ │Trajectory Manager │ │ │
│  │  └──────────┘ └────────┘│  │ │ (100 Hz loop)     │ │ │
│  │  ┌──────────┐ ┌────────┐│  │ └───────────────────┘ │ │
│  │  │  CAM     │ │  NPU   ││  │ ┌───────────────────┐ │ │
│  │  │ Engine   │ │ Infer. ││  │ │TMC5160 SPI Driver │ │ │
│  │  └──────────┘ └────────┘│  │ │ x4 axes (StallG2) │ │ │
│  │  ┌──────────┐           │  │ └───────────────────┘ │ │
│  │  │ Vision   │           │  │ ┌───────────────────┐ │ │
│  │  │ Pipeline │           │  │ │TMC Diagnostics    │ │ │
│  │  └──────────┘           │  │ │ (200 Hz poll)     │ │ │
│  │         RPMsg IPC       │  │ └───────────────────┘ │ │
│  │  <─────────────────────>│  │ ┌───────────────────┐ │ │
│  │                          │  │ │Safety: E-STOP/WDT│ │ │
│  └──────────────────────────┘  │ │ + HW DRV_ENN     │ │ │
│                                 │ └───────────────────┘ │ │
│  ┌────────────┐                └───────────────────────┘ │
│  │ NPU 2.3T   │  Springback ML + Defect Detection       │
│  └────────────┘                                          │
└──────────────────────────────────────────────────────────┘

Motor Axes (TMC5160 via SPI, galvanically isolated ISO7741 x2):
  Phase 1: FEED (axis 0) + BEND (axis 1)
  Phase 2: ROTATE (axis 2) + LIFT (axis 3)
```

### Key Directories
| Path | Description |
|------|-------------|
| `src/app/` | A53 Linux applications (GUI, CAM, NPU, Vision, DB) |
| `src/firmware/` | M7 FreeRTOS firmware (TMC5160 trajectory, diagnostics, safety) |
| `src/shared/` | Shared headers between A53 and M7 |
| `meta-ortho-bender/` | Custom Yocto layer |
| `kas/` | KAS build manifests |
| `tests/` | Unit, integration, system tests |
| `docs/` | Architecture, regulatory, algorithm docs |
| `models/` | ML model training code |
| `tools/` | Development utilities |

### Agents
This project uses claude-dev-forge global agents plus 3 custom agents:
- **motion-control-engineer**: Multi-axis TMC5160 trajectory, StallGuard2 homing
- **cam-algorithm-engineer**: 3D curve -> B-code, springback compensation
- **orthodontic-domain-expert**: Clinical requirements, wire materials

### Regulatory
- FDA Class II 510(k) -- predicate: SureSmile
- IEC 62304 Software Safety Class B
- ISO 13485 QMS
- ISO 14971 Risk Management

### Wire Materials
| Material | Springback | Notes |
|----------|-----------|-------|
| NiTi | High (superelastic) | Needs heating above Af temp |
| SS 304 | Moderate | Standard springback model |
| Beta-Ti (TMA) | Low-moderate | Higher flexibility |
| CuNiTi | High (temp-dependent) | Thermally activated |
