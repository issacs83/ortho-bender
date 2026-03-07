# Ortho-Bender Development Roadmap (Reviewed v1.1)

> Reviewed: 2026-03-07 by architect, firmware-engineer, product-strategist agents
> Original: v1.0 by issacs

---

## Project Overview

YOAT Corporation Bender II / BendArc competitor. In-office orthodontic wire
bending robot combining AI vision + sensorless motor control.
Target: BOM 50% below YOAT, precision 3x better.

## Key Technical Decisions

| Item | Decision | Rationale | Review Notes |
|------|----------|-----------|-------------|
| Main SoC | NXP i.MX8MP | A53x4 + M7 + NPU 2.3TOPS + Dual ISP | OK |
| Motor Driver | TMC5160 (Strategy B) | Built-in motion controller, sensorless | **StallGuard2 (not SG4)** — precision limit |
| Board | 2-board (main + motor) | Galvanic isolation, EMI | OK |
| Isolation | Dual SMPS + ISO7741 | GND separation | **Need ISO7741 x2** (7 lines > 4 channels) |
| Comm | SPI (isolated) | M7 direct to TMC5160 | OK at 4MHz, margin safe |
| Camera | IMX219 5MP MIPI-CSI | NPU vision, $12 | OK |
| Sensor | Sensorless (TMC5160) | Cost reduction | **Add 1 microswitch on BEND axis for fine homing** |
| AI | eIQ + TFLite | NPU INT8 inference | Move to Phase 1-C or Phase 2 |
| Phase | Phase 1 (2D) -> Phase 2 (3D) | 2D MVP first | OK |
| Connector | ~~8-pin~~ **14-16 pin** | SPI+CS4+DRV_ENN+SOL+ESTOP+DIAG+GND | **Changed from 8-pin** |
| Regulatory | FDA Class II 510(k) | IEC 62304 Class B | **Start Month 1, not Month 7** |

## Critical Fixes from Review

### FIX-1: IPC Payload Cannot Carry B-code

- `IPC_MAX_PAYLOAD_SIZE = 256` but 64-step B-code = 776 bytes
- `BCODE_MAX_STEPS = 128` vs `BCODE_SEQUENCE_MAX_STEPS = 64` mismatch
- **Action**: Increase payload to 1024+, unify step count to 128

### FIX-2: AXIS_COUNT Must Be 4

- Currently `AXIS_COUNT = 3` (FEED, ROTATE, BEND)
- Phase 2 adds LIFT — ABI break without pre-planning
- **Action**: `AXIS_MAX = 4`, add `AXIS_LIFT = 3`, use runtime axis mask

### FIX-3: StallGuard2, Not StallGuard4

- TMC5160 has StallGuard**2** (SG4 is TMC2209/TMC2240)
- SG2 works only in SpreadCycle, reproducibility +-2~5 full steps = +-3.6~9 deg
- **Cannot achieve +-0.5 deg with SG alone**
- **Action**: Compound homing strategy (see below)

### FIX-4: PID Redundancy with TMC5160

- TMC5160 has built-in ramp generator + position/velocity loop
- Running M7 PID on top creates dual-loop conflict
- **Action**: M7 becomes trajectory sequence manager, not PID controller
- Keep PID only for optional force control (bend force feedback)

### FIX-5: ISO7741 Channel Count

- SPI 3 lines + CS 4 lines = 7 isolated channels needed
- ISO7741 = 4 channels only
- **Action**: ISO7741 x2, or add CS multiplexer (74HC138)

### FIX-6: E-STOP Dual Path

- SW-only E-STOP insufficient for Class II medical device
- **Action**: Hard-wire E-STOP switch directly to TMC5160 DRV_ENN pin
- Parallel path: M7 GPIO ISR (software) + DRV_ENN (hardware)
- Add external HW watchdog IC (TPS3823) — M7 hang = motor disable

### FIX-7: Regulatory Month 1 Start

- IEC 62304 cannot be applied retroactively
- ISO 13485 QMS required from design phase
- **Action**: QMS framework + DHF writing from Month 1
- Budget $5K-10K for regulatory consultant (part-time)
- FDA classification + Pre-Sub meeting as first priority

## System Architecture (Revised)

```
AC 100~240V
    |
    +-- SMPS 5V/4A -- MAIN BOARD (GND_A)
    |                  +- i.MX8MP SoM
    |                  |   +- A53: Linux, Qt6 UI, NPU, Vision
    |                  |   +- M7: FreeRTOS, SPI Master
    |                  +- ISO7741 x2 (SPI + CS isolation)
    |                  +- IMX219 camera (MIPI-CSI)
    |                  +- 7" touch display
    |                  +- USB 3.0 (oral scanner)
    |
    +-- SMPS 24V/5A -- MOTOR BOARD (GND_B, no MCU)
                        +- TMC5160 #1 FEED
                        +- TMC5160 #2 BEND
                        +- o TMC5160 #3 ROTATE (Phase 2)
                        +- o TMC5160 #4 LIFT (Phase 2)
                        +- MOSFET x2 (solenoid)
                        +- 24V->5V DCDC
                        +- HW Watchdog (TPS3823)
                        +- Microswitch (BEND home)

Inter-board: 14-16 pin connector
  SPI: SCLK, MOSI, MISO (3)
  CS: CS0~CS3 (4, CS2/CS3 Phase 2)
  Control: DRV_ENN, SOL_CLAMP, ESTOP_FB (3)
  Sense: 24V_SENSE, DIAG0 (2)
  Power: GND_ISO (1)
  Reserve: 1-3 pins
```

## M7 Firmware Architecture (Revised)

### Role Change: PID Controller -> Trajectory Sequence Manager

```
Previous:                          Revised:
M7 PID loop (1kHz)                 M7 trajectory manager
  -> step/dir pulse gen              -> TMC5160 XTARGET register write
  -> encoder feedback                 -> SG_RESULT/DRV_STATUS monitoring
  -> current sensing                  -> safety decision + A53 reporting
```

### Task Architecture

```
safety_task  (pri 6, 10kHz) - E-STOP GPIO + SW flags only (NO SPI)
motion_task  (pri 5, 100Hz) - TMC5160 register control, trajectory sequencing
tmc_poll_task(pri 4, 200Hz) - TMC5160 DRV_STATUS/SG_RESULT polling via SPI
ipc_task     (pri 3, event) - RPMsg command processing
status_task  (pri 2, 10Hz)  - Status reporting to A53
```

Key changes:
- `sensor_task` renamed to `tmc_poll_task` (sensorless = TMC register polling)
- `motion_task` reduced to 100Hz (TMC5160 internal ramp handles real-time)
- `safety_task` does NOT use SPI (avoids blocking motion SPI)
- Stack sizes: motion 2048 words, ipc 1536 words, others 512 words

### TMC5160 Driver Module (New)

```
tmc5160_driver.c/.h
  - SPI 40-bit transaction (8-bit addr + 32-bit data)
  - Init sequence: GCONF, CHOPCONF, IHOLD_IRUN, PWMCONF, RAMPMODE
  - Motion: XTARGET, VMAX, AMAX, DMAX (S-curve via internal ramp)
  - StallGuard2: SG threshold set/read, stall detect
  - CoolStep: current scaling parameters
  - Diagnostics: DRV_STATUS, TSTEP, SG_RESULT readback
  - SPI Mode 3 (CPOL=1, CPHA=1), CS setup delay 50ns after assert
```

### Compound Homing Strategy

```
1. Coarse: StallGuard2 -> find mechanical stop (fast speed)
2. Backoff: Retract fixed distance
3. Fine: Microswitch for precise home (BEND axis)
4. Zero: Reset TMC5160 internal step counter
5. Track: XACTUAL register for position tracking
6. Periodic: Compare against known stop for drift correction
```

## Revised Timeline (12-14 months)

### Phase 1-A: Foundation (Month 1-3)

**Goal: HW platform + basic motor + QMS start**

```
Month 1: Procurement + Regulatory Start
  [] SoM EVK order (Variscite DART-MX8MP + Symphony carrier)
  [] TMC5160-BOB eval boards x2
  [] NEMA 17 stepper + planetary gear
  [] IMX219 camera module
  [] 7" LVDS touch display
  [] QMS framework setup (design control, risk mgmt)
  [] FDA classification research + predicate device search
  [] FTO patent search initiation ($5K-15K)
  [] DHF writing begins (concurrent with development)

Month 2: SW Foundation + Motor Standalone Test
  [] Yocto BSP build (kas)
  [] M7 FreeRTOS boot + RPMsg verify
  [] TMC5160 SPI comm test on EVK
    - Register read/write through ISO7741
    - Position mode basic operation
    - StallGuard2 threshold initial tuning
  [] Camera V4L2 streaming verify
  [] Fix ipc_protocol.h critical issues (payload size, axis count)
  [] FTO results review

Month 3: Mechanical Prototype + Board Design
  [] 3D printed mechanism v1 (bend die + roller + clamp)
  [] Motor + gearbox assembly
  [] TMC5160 -> motor direct drive test
    - S-curve acceleration tuning (internal ramp generator)
    - Compound homing sequence validation
    - Wire insertion detection (Nudge Test)
  [] Main board carrier PCB design (4-layer)
    - SoM connector + MIPI-CSI + LVDS
    - ISO7741 x2 isolation circuit
    - TLP291 photocoupler (SOL + ESTOP)
  [] Motor board PCB design (2-layer)
    - TMC5160 x2 (+ Phase 2 footprints x2 unpopulated)
    - MOSFET solenoid driver
    - HW watchdog (TPS3823)
    - 24V->5V DCDC
  [] PCB order (JLCPCB/PCBWay, ~2 week lead)
```

### Phase 1-B: Integration + First Bending (Month 4-6)

**Goal: 2D bending + camera vision basic pipeline (+-2 deg)**

```
Month 4: Board Assembly + HW Integration
  [] Main board + motor board assembly + power-on test
  [] Isolated SPI verify (through ISO7741)
  [] E-STOP dual-path verify (SW ISR + HW DRV_ENN)
  [] HW watchdog verify (TPS3823)
  [] Dual SMPS power stability test
  [] Mechanism v2 assembly (with boards)

Month 5: M7 Firmware Core
  [] TMC5160 driver complete (tmc5160_driver.c/.h)
    - SPI read/write (isolated)
    - Motion commands (position/velocity/stop via internal ramp)
    - StallGuard2 compound homing
    - Wire insertion detection (Nudge Test)
    - Torque monitoring (SG_RESULT, CS_ACTUAL)
  [] Solenoid control (CLAMP ON/OFF)
  [] RPMsg command protocol implementation
    - A53 -> M7: bend_point_t commands
    - M7 -> A53: status/torque data reporting
  [] Wire material presets (SS/TMA/NiTi)
  [] Unit tests for TMC5160 driver (mock SPI)

Month 6: A53 Software + First Bending
  [] Camera pipeline (GStreamer: MIPI-CSI -> ISP -> preview)
  [] OpenCV: ROI crop + Canny + Hough (angle measurement)
  [] Lighting control (backlight/ring LED GPIO)
  [] Qt6 UI prototype
    - Live camera preview
    - Wire material selection
    - Bend start/stop/home buttons
    - SG/CS real-time graph
  [] Springback LUT construction
    - SS 0.016x0.022 baseline: 10-120 deg range, 5 deg intervals
    - Camera-based direct measurement
  [] FIRST RETAINER BENDING TEST!
    - 3-to-3 fixed retainer (8 bend points)
    - Target: +-2 deg precision
```

### Phase 1-C: Precision + Product Polish (Month 7-9)

**Goal: +-0.5 deg precision, alpha testing, UI complete**

```
Month 7: Precision Refinement
  [] Adaptive springback compensation (adaptive_gain)
  [] Camera-based springback direct measurement
    - Continuous frame: die max -> springback angle difference
  [] Material-specific calibration routines
  [] Compound homing precision validation
  [] Rule-based QC (camera angle check vs target, PASS/WARN/FAIL)
  [] Target: +-1 deg

Month 8: Alpha Internal Testing
  [] 500+ bending cycle reliability test (MTBF target)
  [] Wire material coverage (SS, TMA, NiTi, CuNiTi)
  [] Qt6 UI completion
    - STL file load -> bend path
    - Wire insertion guide
    - Bending progress monitoring
    - QC result view
    - Calibration menu
    - Settings (material, current, speed presets)
  [] Auto-calibration routine (checkerboard intrinsic + reference bend)
  [] Target: +-0.5 deg

Month 9: Product Readiness
  [] Bending timelapse recording (VPU H.265)
  [] QC report PDF generation
  [] 100+ retainer continuous production stability test
  [] Housing design + prototype
  [] User manual draft
  [] 510(k) documentation progress review
```

### Phase 1-D: Beta + Market Entry (Month 10-14)

**Goal: Beta test + regulatory submission**

```
Month 10-11: Beta Deployment
  [] Beta units 5-10 production
  [] Alpha test (internal): 1,000+ bending cycles verified
  [] Beta test (external): 5-10 clinics, 8 weeks, 50+ bends/clinic
  [] Beta success criteria:
    - +-0.5 deg achievement rate >= 95%
    - User satisfaction NPS >= 40
    - Note: fitting on models only (not in-mouth) until regulatory clear
  [] Clinical feedback collection

Month 12-14: Regulatory + Launch Prep
  [] Bug fixes + optimization from beta
  [] 510(k) submission preparation
  [] MFDS Class I application (Korea)
  [] DFM review for mass production
  [] Production BOM finalization + component sourcing
  [] Liability insurance
  [] Distribution channel confirmation (D2C or dealer)
```

### Phase 2: 3D Extension (Month 15-18)

```
  [] ROTATE axis module design/build
  [] TMC5160 #3 populate on motor board
  [] M7 firmware: ROTATE axis activation (config change only)
  [] 3D bend path planner
  [] 3D springback LUT expansion
  [] Dual camera (stereo vision or macro inspection)
  [] NPU vision models (wire segmentation, angle measurement)
  [] Auto QC with AR overlay
  [] Time-series AI (kink/slip prediction, springback neural net)
```

### Phase 3: Service + Scale (Month 19-24)

```
  [] Cloud service (3D scan -> AI bend path optimization API)
  [] OTA model update pipeline
  [] Fleet learning (multi-device data -> global precision improvement)
  [] Voice commands (Whisper Tiny)
  [] Mass production line (500-1,000 units)
  [] Global certification (CE, FDA clearance, MFDS)
```

## Risk Matrix (Revised)

| # | Risk | Severity | Probability | Mitigation |
|---|------|----------|-------------|------------|
| 1 | StallGuard2 homing imprecision | High | High | Compound homing + microswitch on BEND |
| 2 | M7 hang -> motor runaway | High | Low | HW watchdog + DRV_ENN hard-wire to E-STOP |
| 3 | Regulatory delay (510(k)) | High | Medium | Start Month 1, consultant, Pre-Sub meeting |
| 4 | Patent infringement (YOAT/OraMetrix) | High | Medium | FTO search Month 1-2 ($5K-15K) |
| 5 | Springback compensation precision | High | Medium | Camera direct measurement + adaptive learning |
| 6 | Distribution channel absence | High | High | D2C online or dealer partnership early |
| 7 | Timeline overrun (2-person team) | Medium | High | Phase 1-C scope reduction, rule-based QC first |
| 8 | Mechanism precision (3D printing) | Medium | High | CNC for critical parts only |
| 9 | Wire material SG variance | Medium | Medium | Per-material calibration routine |
| 10 | i.MX8MP supply chain (lead time) | Medium | Medium | Identify alternative SoC, safety stock |
| 11 | ISO7741 SPI instability | Low | Low | Verified part, 4MHz << 15MHz max |
| 12 | YOAT price response | Medium | Medium | Maintain cost advantage, add SaaS revenue |

## Cost Summary (Revised)

| Category | Phase 1 (2D) | Notes |
|----------|-------------|-------|
| Product BOM (production) | ~$730 | Kit sale possible |
| Fully loaded cost | ~$1,200-1,500 | + certification, tooling, packaging, insurance |
| Prototype cost | ~$2,000-3,000 | EVK, PCB proto, 3D printing |
| Dev tools/equipment | ~$1,000-2,000 | Oscilloscope, power supply, etc. |
| Regulatory consultant | ~$5,000-10,000 | Part-time, FDA + QMS guidance |
| FTO patent search | ~$5,000-15,000 | Freedom-to-operate analysis |
| Software licenses | $0 | Full open-source stack |
| Retail price target | **$3,999** | Sub-$4K psychological threshold |
| Subscription (Phase 1+) | $49-99/month | Wire presets, recipes, updates |

## Product Positioning

| Aspect | YOAT Bender II | Ours (Phase 1) |
|--------|---------------|----------------|
| Camera | None | AI vision (NPU 2.3 TOPS) |
| Motor control | Open-loop stepper | TMC5160 sensorless closed-loop |
| Springback | Fixed LUT | Camera measurement + adaptive learning |
| QC | Manual (visual) | Rule-based auto QC + report |
| Calibration | Technician | 5-min auto calibration |
| Form factor | PC + MCU separate | i.MX8MP all-in-one (compact) |
| Wire types | Dedicated machine per type | Software preset switching |
| Est. BOM | $4,000-8,000 (unverified) | ~$730 |
| Est. retail | $15,000-25,000 (unverified) | $3,999 |
| Product name | Bender II | **Automated Retainer Bender** |
| Capability | 3D bending | 2D (Phase 1), 3D (Phase 2) |

> Note: YOAT pricing is estimated, not publicly verified.
> Phase 1 comparison is specifically for retainer bending use case.

## Immediate Action Items (P0)

1. Fix `ipc_protocol.h`: payload size 1024+, step count unify to 128
2. Fix `ipc_protocol.h`: `AXIS_MAX = 4` with runtime axis mask
3. Fix `machine_config.h`: BEND = stepper, remove PID for position control
4. Correct roadmap: StallGuard2 (not SG4) + compound homing strategy
5. Change connector to 14-16 pin, ISO7741 x2 design
6. Start QMS/DHF from Month 1
7. Initiate FTO patent search
8. Add CRC-32 to `ipc_msg_header_t` for safety commands
9. Fix `timestamp_us` overflow (uint64 or relative)
