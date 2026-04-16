# Motor Driver Test Bench Design Specification

**Date**: 2026-04-16
**Author**: Isaac Park / Project Director
**Status**: Approved
**Task**: #23 - Motor Driver Test Bench Connection Plan

---

## 1. Purpose and Scope

Validate three motor driver test boards on the i.MX8MP EVK via the J21 header
before committing to the production adapter board design. This bench serves two
goals:

1. **Hardware validation** -- confirm SPI communication, STEP/DIR pulse
   generation, and StallGuard2 sensorless homing with real Trinamic drivers.
2. **Software architecture proof** -- exercise the full FastAPI/React/M7 stack
   end-to-end so that bending SW developers have a tested API from day one.

### Test Boards

| Board | IC | SPI Bits | VS Range | I_rms | Motion Mode |
|-------|----|----------|----------|-------|-------------|
| DRI0035 #1 | TMC260C | 20-bit | 7--40 V | 2 A | STEP/DIR (external) |
| DRI0035 #2 | TMC260C | 20-bit | 7--40 V | 2 A | STEP/DIR (external) |
| TMC5072-BOB | TMC5072-LA | 40-bit | 5--26 V | 1.1 A x2 | Internal ramp (SPI position) |

### Out of Scope

- Production adapter board fabrication (separate task)
- Phase 2 axes (ROTATE, LIFT) -- only FEED + BEND are wired
- NiTi thermal control
- NPU inference pipeline

---

## 2. Hardware Topology

### 2.1 SPI Bus: Split Chip-Select (NOT Daisy-Chain)

The production architecture document (`docs/architecture/motor-control-architecture.md`
Section 5.2) proposes a 160-bit daisy-chain assuming all drivers use 40-bit datagrams.
**This is incorrect**: TMC260C uses 20-bit datagrams and cannot share a chain with
40-bit devices.

**Test bench topology**: separate CS per device, shared MOSI/MISO/SCLK bus.

```
                    ECSPI2 (i.MX8MP)
                    ┌─────────┐
                    │ MOSI ───┼──────────────┬──────────────┬──────────┐
                    │ MISO ───┼──────────────┼──────────────┼──────────┤
                    │ SCLK ───┼──────────────┼──────────────┼──────────┤
                    │ SS0  ───┼── CS0 ──────▶│ DRI0035 #1   │          │
                    │         │              │ (TMC260C)    │          │
                    └─────────┘              └──────────────┘          │
                         │                                             │
                    GPIO3_IO19 ── CS1 ──────▶ DRI0035 #2 (TMC260C)    │
                                                                       │
                    GPIO3_IO20 ── CS2 ──────▶ TMC5072-BOB (TMC5072-LA)
```

**SPI parameters**: 2 MHz, SPI Mode 3 (CPOL=1, CPHA=1), MSB first.

### 2.2 Signal Level Translation

The i.MX8MP SoC operates at 1.8 V I/O on J21. The DRI0035 and TMC5072-BOB
expect 5 V and 3.3 V logic respectively. A SparkFun TXS0108E breakout board
provides 8-channel bidirectional auto-direction level shifting.

**TXS0108E channel allocation**:

| TXS Ch | Signal | Direction | J21 Pin | SoC Pad |
|--------|--------|-----------|---------|---------|
| 1 | SPI MOSI | SoC -> Driver | 19 | ECSPI2_MOSI |
| 2 | SPI SCLK | SoC -> Driver | 23 | ECSPI2_SCLK |
| 3 | CS0 (DRI0035 #1) | SoC -> Driver | 24 | ECSPI2_SS0 |
| 4 | CS1 (DRI0035 #2) | SoC -> Driver | 37 | GPIO3_IO19 |
| 5 | FEED STEP | SoC -> Driver | 31 | GPIO3_IO22 |
| 6 | BEND STEP | SoC -> Driver | 36 | GPIO3_IO24 |
| 7 | DIR (shared) | SoC -> Driver | 8 | GPIO5_IO06 |
| 8 | (spare) | -- | -- | -- |

**MISO path**: resistor divider (4.7 kOhm series per DRI0035 + 10 kOhm
pull-down to GND) converts 5 V MISO to ~3.3 V, safe for J21 pin 21
(ECSPI2_MISO) via NTB0104 on-board level shifter.

**TMC5072-BOB CS2**: connected directly at 3.3 V (no TXS channel needed;
TMC5072 VCC_IO set to 3.3 V via its P1 header, and a 10 kOhm pull-up to
3.3 V on pin 35/GPIO3_IO20 is sufficient).

### 2.3 J21 Pin Assignment (Test Bench)

| J21 Pin | SoC Pad | i.MX8MP GPIO | Function | Notes |
|---------|---------|-------------|----------|-------|
| 19 | ECSPI2_MOSI | -- | SPI MOSI | TXS ch1, 1.8V -> 5V |
| 21 | ECSPI2_MISO | -- | SPI MISO | Resistor divider 5V -> ~3.3V |
| 23 | ECSPI2_SCLK | -- | SPI SCLK | TXS ch2 |
| 24 | ECSPI2_SS0 | -- | CS0: DRI0035 #1 | TXS ch3 |
| 37 | SAI5_RXD3 | GPIO3_IO19 | CS1: DRI0035 #2 | TXS ch4 |
| 35 | SAI5_RXD2 | GPIO3_IO20 | CS2: TMC5072-BOB | Direct 3.3V |
| 31 | SAI5_RXD0 | GPIO3_IO22 | FEED STEP | TXS ch5 |
| 36 | SAI5_MCLK | GPIO3_IO24 | BEND STEP | TXS ch6 |
| 8 | ECSPI1_MISO | GPIO5_IO06 | DIR (shared) | TXS ch7 |
| 10 | ECSPI1_SS0 | GPIO5_IO07 | SG_IN (optional) | NTS0104, input only |

**Forbidden pins**:
- Pin 7 (GPIO3_IO21): EVK LED D14 conflict
- Pin 12 (GPIO3_IO24): same SoC pad as pin 36 -- cannot use both
- Pin 10 for output: NTS0104 U56 is J21-to-SoC direction only

**GPIO budget constraint**: only 6 output-capable GPIOs are available on J21.
With 3 CS + 2 STEP + 1 DIR = 6, the budget is exactly consumed. FEED and BEND
share a single DIR line. This is acceptable because the test bench operates in
sequential single-axis mode (S1--S4) and coordinated 2-axis mode only for
FEED+BEND sync (S5), where both axes share direction context.

### 2.4 Shield Construction

Proto board (만능기판) mounted as a shield over J21:
- TXS0108E breakout in center
- 3x JST-XH connectors for DRI0035 SPI + DRI0035 SPI + TMC5072 SPI
- 2x 4-pin connectors for STEP/DIR (FEED, BEND)
- MISO resistor divider on-board
- 10 kOhm pull-up on CS2 line
- Power rails: 3.3 V from J21 pin 1, 5 V from J21 pin 2

### 2.5 Power

| Domain | Voltage | Source | Consumers |
|--------|---------|--------|-----------|
| VCC_IO (TXS A-side) | 1.8 V | J21 pin 17 (1V8) | TXS0108E VA |
| VCC_IO (TXS B-side) | 5 V | J21 pin 2 (5V) | TXS0108E VB |
| VCC_IO (TMC5072) | 3.3 V | J21 pin 1 (3V3) | TMC5072-BOB P1 |
| V_MOTOR (DRI0035) | 12 V | External bench PSU | DRI0035 VMOT |
| V_MOTOR (TMC5072) | 12 V | External bench PSU | TMC5072-BOB P12 |

---

## 3. Software Architecture

### 3.1 System Layer View

```
Layer 5: Frontend (React)
  DiagnosticsPage: RegisterInspector, StallGuardChart, SPI test, jog controls
         |
         | HTTP REST + WebSocket
         v
Layer 4: Backend (Python FastAPI, A53 Linux)
  motor_router.py    -- existing motion API (/api/motor/*)
  diag_router.py     -- NEW diagnostic API (/api/motor/diag/*)
  motor_service.py   -- existing motion service
  diag_service.py    -- NEW diagnostic service
  spi_backend.py     -- NEW spidev direct SPI driver (test bench mode)
  ipc_client.py      -- existing RPMsg transport (production mode)
         |
         | OB_MOTOR_BACKEND selects transport
         v
Layer 3: Transport Switch
  "mock"   -> MockMotorBackend    (no hardware, simulated responses)
  "spidev" -> SpidevMotorBackend  (Python spidev, direct ECSPI2, test bench)
  "m7"     -> IpcMotorBackend     (RPMsg to M7, production)
         |
         v
Layer 2: Shield + Level Shifters
  TXS0108E (1.8V <-> 5V) + resistor divider (MISO)
         |
         v
Layer 1: Motor Drivers
  DRI0035 #1 (TMC260C, 20-bit SPI, STEP/DIR)
  DRI0035 #2 (TMC260C, 20-bit SPI, STEP/DIR)
  TMC5072-BOB (TMC5072-LA, 40-bit SPI, internal ramp)
         |
         v
Layer 0: Stepper Motors
  NEMA17 x2 (bench test motors)
```

### 3.2 Three-Mode Motor Backend

A new `OB_MOTOR_BACKEND` environment variable selects the transport layer.
This enables the same API and frontend to work in three scenarios:

| Mode | `OB_MOTOR_BACKEND` | Hardware Required | Use Case |
|------|--------------------|-------------------|----------|
| Mock | `mock` (default) | None | Desktop development, CI tests |
| Spidev | `spidev` | EVK + shield + drivers | Test bench validation |
| M7 | `m7` | Full production board | Production deployment |

**Backend interface** (Python abstract class):

```python
class MotorBackend(ABC):
    @abstractmethod
    async def spi_transfer(self, cs: int, data: bytes) -> bytes: ...

    @abstractmethod
    async def set_gpio(self, pin: str, value: bool) -> None: ...

    @abstractmethod
    async def get_gpio(self, pin: str) -> bool: ...

    @abstractmethod
    async def pulse_step(self, axis: int, count: int,
                         freq_hz: int, direction: int) -> None: ...
```

**Spidev backend** (`spi_backend.py`):
- Opens `/dev/spidev1.0` (ECSPI2, CS0) for DRI0035 #1
- Uses GPIO-based CS for DRI0035 #2 (CS1) and TMC5072 (CS2)
- STEP pulse generation via Python `time.sleep` loop (adequate for bench test
  speeds up to 1 kHz; production uses M7 GPT timer ISR at 100 kHz+)
- Implements TMC260C 20-bit and TMC5072 40-bit datagram framing

### 3.3 SPI Protocol Drivers

Two driver classes encapsulate the different datagram formats:

**Tmc260cDriver** (20-bit):
```python
class Tmc260cDriver:
    def __init__(self, backend: MotorBackend, cs: int): ...
    async def write_register(self, reg_tag: int, value: int) -> int: ...
    async def read_status(self) -> Tmc260cStatus: ...
    async def set_current(self, scale: int) -> None: ...
    async def set_microstep(self, mres: int) -> None: ...
    async def set_stallguard(self, threshold: int, filter: bool) -> None: ...
```

**Tmc5072Driver** (40-bit):
```python
class Tmc5072Driver:
    def __init__(self, backend: MotorBackend, cs: int): ...
    async def read_register(self, addr: int) -> int: ...
    async def write_register(self, addr: int, value: int) -> None: ...
    async def move_to(self, motor: int, position: int,
                      vmax: int, amax: int) -> None: ...
    async def get_position(self, motor: int) -> int: ...
    async def get_drv_status(self, motor: int) -> int: ...
```

### 3.4 Diagnostic API

New endpoints under `/api/motor/diag/` for low-level driver access:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/motor/diag/spi-test` | Send known pattern, verify echo |
| GET | `/api/motor/diag/register/{driver}/{addr}` | Read single TMC register |
| POST | `/api/motor/diag/register/{driver}/{addr}` | Write single TMC register |
| GET | `/api/motor/diag/dump/{driver}` | Dump all status registers |
| POST | `/api/motor/diag/stallguard/calibrate` | Run SG2 calibration sequence |
| GET | `/api/motor/diag/stallguard/stream` | SSE stream of SG2 values (200 Hz) |
| GET | `/api/motor/diag/backend` | Return current backend mode + config |

**Path parameters**:
- `driver`: `"tmc260c_0"` | `"tmc260c_1"` | `"tmc5072"`
- `addr`: register address (hex string, e.g. `"0x6A"`)

**Diagnostic WebSocket**: `/ws/motor/diag`
- 200 Hz TMC status stream (DRV_STATUS, SG_RESULT, position)
- JSON messages matching existing `WsMotorEvent` structure with extended fields

### 3.5 Configuration Extensions

New fields in `config.py` (all with `OB_` prefix):

```python
# Motor backend
motor_backend: str = "mock"           # "mock" | "spidev" | "m7"

# SPI (spidev mode only)
spi_device: str = "/dev/spidev1.0"    # ECSPI2 bus
spi_speed_hz: int = 2_000_000         # 2 MHz (TMC260C limit)

# GPIO (spidev mode only)
gpio_cs1: str = "GPIO3_IO19"          # CS for DRI0035 #2
gpio_cs2: str = "GPIO3_IO20"          # CS for TMC5072
gpio_feed_step: str = "GPIO3_IO22"
gpio_bend_step: str = "GPIO3_IO24"
gpio_dir: str = "GPIO5_IO06"
```

### 3.6 M7 Firmware Additions

For production (`OB_MOTOR_BACKEND=m7`), the M7 firmware needs:

1. **tmc5072_ops.c** -- new vtable implementing `motor_hal_ops_t` for TMC5072:
   - `init`: configure GCONF, CHOPCONF, IHOLD_IRUN for both motors
   - `move_abs`: write XTARGET register, set VMAX/AMAX
   - `position_reached`: read RAMP_STAT.position_reached bit
   - `get_position`: read XACTUAL register
   - `poll_status`: read DRV_STATUS, SG_RESULT

2. **Split CS SPI topology**: modify `tmc_spi_task` to select per-driver CS
   and use correct datagram size (20-bit for TMC260C, 40-bit for TMC5072).

3. **IPC extensions**: existing `MSG_DIAG_TMC_READ` (0x0200) / `MSG_DIAG_TMC_WRITE`
   (0x0201) already support per-axis register access. The `axis` field maps to
   CS selection. No protocol changes needed.

---

## 4. Integration Plan (Files to Modify/Create)

### 4.1 New Files

| File | Description |
|------|-------------|
| `src/app/server/services/motor_backend.py` | Abstract backend + mock implementation |
| `src/app/server/services/spi_backend.py` | Spidev backend (Python SPI + GPIO) |
| `src/app/server/services/tmc260c_driver.py` | TMC260C 20-bit protocol driver |
| `src/app/server/services/tmc5072_driver.py` | TMC5072 40-bit protocol driver |
| `src/app/server/services/diag_service.py` | Diagnostic service layer |
| `src/app/server/routers/diag_router.py` | Diagnostic REST endpoints |
| `src/app/server/models/diag_schemas.py` | Diagnostic request/response Pydantic models |
| `src/app/frontend/src/pages/DiagnosticsPage.tsx` | Test bench diagnostic UI |
| `src/app/frontend/src/components/RegisterInspector.tsx` | TMC register R/W panel |
| `src/app/frontend/src/components/StallGuardChart.tsx` | Real-time SG2 chart |
| `src/firmware/source/drivers/tmc5072.h` | TMC5072 register definitions + driver API |
| `src/firmware/source/drivers/tmc5072.c` | TMC5072 driver implementation |
| `src/firmware/source/drivers/tmc5072_hal_ops.c` | motor_hal_ops_t for TMC5072 |
| `tests/test_tmc260c_driver.py` | TMC260C protocol unit tests |
| `tests/test_tmc5072_driver.py` | TMC5072 protocol unit tests |
| `tests/test_diag_service.py` | Diagnostic service unit tests |

### 4.2 Modified Files

| File | Changes |
|------|---------|
| `src/app/server/config.py` | Add `motor_backend`, `spi_device`, `spi_speed_hz`, GPIO pin fields |
| `src/app/server/main.py` | Add backend factory in lifespan, mount `diag_router` |
| `src/app/server/services/motor_service.py` | Accept `MotorBackend` in constructor alongside `IpcClient` |
| `src/app/server/models/schemas.py` | Add `DiagRegisterRequest`, `DiagRegisterResponse`, `SpiTestResult` |
| `src/app/server/ws/manager.py` | Add `/ws/motor/diag` broadcast channel (200 Hz) |
| `src/app/frontend/src/api/client.ts` | Add `diagApi` object + `wsApi.motorDiag` |
| `src/app/frontend/src/App.tsx` | Add route for `/diagnostics` page |
| `docs/architecture/motor-control-architecture.md` | Fix Section 5.2: split CS replaces daisy-chain |

---

## 5. Frontend UI

### 5.1 DiagnosticsPage Layout

```
+-------------------------------------------------------------------+
|  [DIAGNOSTICS]                          Backend: spidev | 2 MHz   |
+-------------------------------------------------------------------+
|                                                                     |
|  +--[ SPI Test ]--+  +--[ Register Inspector ]------------------+  |
|  | [Run SPI Test] |  | Driver: [tmc260c_0 v]  Addr: [0x__]     |  |
|  | Result: OK     |  | Value:  [0x_____]  [Read] [Write]        |  |
|  | Latency: 42 us |  | Last:   CHOPCONF = 0x000101D5            |  |
|  +-----------------+  +------------------------------------------+  |
|                                                                     |
|  +--[ StallGuard2 Live Chart ]----------------------------------+  |
|  |  1023 |                                                       |  |
|  |       |   ~~~~~~                     ~~~                      |  |
|  |       |         ~~~~           ~~~~~    ~~~                   |  |
|  |     0 |_______________~~~~~~__________     ~~~~_______________  |
|  |       0s                                                 10s  |  |
|  |  [tmc260c_0: 412]  [tmc260c_1: 387]  Threshold: ----         |  |
|  +---------------------------------------------------------------+  |
|                                                                     |
|  +--[ Motor Jog ]-----------------------------------------------+  |
|  | Axis: [FEED v]  Speed: [___] mm/s  Steps: [___]              |  |
|  |  [<< REV]  [STOP]  [FWD >>]                                  |  |
|  | Position: 0.000 mm  |  SG: 412  |  Status: IDLE              |  |
|  +---------------------------------------------------------------+  |
|                                                                     |
|  +--[ Register Dump ]-------------------------------------------+  |
|  | [Dump tmc260c_0] [Dump tmc260c_1] [Dump tmc5072]            |  |
|  | DRVCTRL  = 0x00009 | CHOPCONF = 0x101D5 | SMARTEN = 0xA0000 |  |
|  | SGCSCONF = 0xD0014 | DRVCONF  = 0xE0050 |                    |  |
|  +---------------------------------------------------------------+  |
+-------------------------------------------------------------------+
```

### 5.2 Key UI Features

1. **SPI Test Button**: sends known 20-bit pattern, verifies response matches
   expected status format (validates wiring + level shifter + driver power).

2. **Register Inspector**: read/write any TMC register by address. Dropdown
   selects driver (`tmc260c_0`, `tmc260c_1`, `tmc5072`). Shows decoded field
   names on hover.

3. **StallGuard2 Live Chart**: Recharts line chart fed by `/ws/motor/diag`
   WebSocket at 200 Hz. Shows SG values for all connected drivers overlaid.
   Horizontal threshold line for homing calibration.

4. **Motor Jog Controls**: axis selector, speed input, forward/reverse buttons.
   Shows real-time position and SG value. E-STOP button always visible.

5. **Register Dump**: one-click full register dump per driver. Displayed as
   formatted table with register names and hex values.

---

## 6. Developer API Guide

### 6.1 Quick Start

Bending SW developers interact with hardware exclusively through the REST API.
The `OB_MOTOR_BACKEND` environment variable controls which transport is active.
The API surface is identical in all modes.

```bash
# Start backend in mock mode (no hardware)
OB_MOTOR_BACKEND=mock uvicorn src.app.server.main:create_app --factory

# Start backend with test bench shield
OB_MOTOR_BACKEND=spidev OB_SPI_DEVICE=/dev/spidev1.0 uvicorn ...

# Start backend with M7 (production)
OB_MOTOR_BACKEND=m7 OB_IPC_DEVICE=/dev/rpmsg0 uvicorn ...
```

### 6.2 Sample Code (Python httpx)

```python
import httpx
import asyncio

BASE = "http://192.168.77.2:8000"

async def main():
    async with httpx.AsyncClient(base_url=BASE) as c:
        # 1. Check backend mode
        r = await c.get("/api/motor/diag/backend")
        print(r.json())  # {"success": true, "data": {"backend": "spidev", ...}}

        # 2. SPI connectivity test
        r = await c.get("/api/motor/diag/spi-test")
        print(r.json())  # {"success": true, "data": {"tmc260c_0": "ok", ...}}

        # 3. Read TMC260C CHOPCONF register
        r = await c.get("/api/motor/diag/register/tmc260c_0/0x04")
        print(r.json())  # {"success": true, "data": {"value": "0x101D5"}}

        # 4. Jog FEED axis forward at 10 mm/s
        r = await c.post("/api/motor/jog", json={
            "axis": 0, "direction": 1, "speed": 10.0, "distance": 50.0
        })
        print(r.json())

        # 5. Home FEED axis (StallGuard2)
        r = await c.post("/api/motor/home", json={"axis_mask": 0x01})
        print(r.json())

        # 6. Execute 3-step B-code sequence
        r = await c.post("/api/bending/execute", json={
            "steps": [
                {"L_mm": 10.0, "beta_deg": 0, "theta_deg": 30.0},
                {"L_mm": 15.0, "beta_deg": 0, "theta_deg": 45.0},
                {"L_mm": 10.0, "beta_deg": 0, "theta_deg": 0.0},
            ],
            "material": 0,
            "wire_diameter_mm": 0.457
        })
        print(r.json())

asyncio.run(main())
```

### 6.3 WebSocket Monitoring

```python
import asyncio
import websockets
import json

async def monitor_sg():
    uri = "ws://192.168.77.2:8000/ws/motor/diag"
    async with websockets.connect(uri) as ws:
        async for msg in ws:
            data = json.loads(msg)
            for ax in data.get("axes", []):
                print(f"Axis {ax['axis']}: SG={ax['sg_result']}, pos={ax['position']}")

asyncio.run(monitor_sg())
```

---

## 7. Test Plan (5 Stages)

### S1: TMC260C SPI Verification

**Goal**: confirm 20-bit SPI communication with DRI0035 #1.

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 1.1 | Power DRI0035 (12 V + VCC_IO) | LED on board lit |
| 1.2 | Send CHOPCONF default via `/api/motor/diag/register/tmc260c_0/0x04` | Response bits [19:17] match CHOPCONF tag |
| 1.3 | Read back CHOPCONF | Value matches written default (0x101D5) |
| 1.4 | Set DRVCONF RDSEL=StallGuard | Response contains SG value field |
| 1.5 | Dump all registers via `/api/motor/diag/dump/tmc260c_0` | 5 registers decoded without error |
| 1.6 | Repeat 1.1--1.5 for DRI0035 #2 (tmc260c_1) | Same criteria |

### S2: TMC5072 SPI Verification

**Goal**: confirm 40-bit SPI communication with TMC5072-BOB.

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 2.1 | Power TMC5072-BOB (12 V + 3.3 V VCC_IO) | No fault LEDs |
| 2.2 | Read GCONF register (addr 0x00) | Returns valid GCONF value |
| 2.3 | Write CHOPCONF for motor 0 | Read-back matches |
| 2.4 | Read IC_VERSION register (addr 0x73) | Returns TMC5072 ID (0x02xx) |
| 2.5 | Configure IHOLD_IRUN, write XTARGET | XACTUAL changes toward XTARGET |

### S3: STEP/DIR Motor Control

**Goal**: spin NEMA17 motors via DRI0035 STEP/DIR pins.

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 3.1 | Configure TMC260C via SPI (current, microstep) | No fault in response |
| 3.2 | Jog FEED axis +100 steps at 200 Hz | Motor rotates, position increments |
| 3.3 | Jog FEED axis -100 steps | Motor reverses, position decrements |
| 3.4 | Repeat for BEND axis | Same criteria |
| 3.5 | Verify StallGuard2 reading during motion | SG value varies with load (hand resistance) |

### S4: StallGuard2 Homing

**Goal**: validate sensorless homing using SG2 stall detection.

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 4.1 | Open SG2 live chart on DiagnosticsPage | Chart shows real-time SG values |
| 4.2 | Calibrate SG threshold (jog at low speed, note SG at stall) | Threshold identified |
| 4.3 | Set SG threshold via `/api/motor/diag/stallguard/calibrate` | Threshold stored |
| 4.4 | Execute homing via `/api/motor/home` | Motor moves until stall, position resets to 0 |
| 4.5 | Repeat homing 5x | Position repeatability within 2 full steps |

### S5: 2-Axis Synchronization

**Goal**: validate FEED + BEND sequential operation (B-code execution).

| Step | Action | Pass Criteria |
|------|--------|---------------|
| 5.1 | Execute 3-step B-code: Feed 10 mm, Bend 30 deg, Feed 15 mm, Bend 45 deg | Sequence completes without fault |
| 5.2 | Monitor via `/ws/motor` during execution | State transitions: IDLE -> RUNNING -> IDLE |
| 5.3 | Verify final positions | Within 1% of commanded values |
| 5.4 | E-STOP during execution | Immediate halt, state -> ESTOP |
| 5.5 | Reset after E-STOP | State -> IDLE, drivers re-enabled |

---

## 8. Purchase List

| # | Item | Qty | Purpose |
|---|------|-----|---------|
| 1 | SparkFun TXS0108E breakout (BOB-11771) | 1 | 8-ch level shifter |
| 2 | 만능기판 (70x50mm) | 1 | Shield substrate |
| 3 | 2.54mm pin header (2x20) | 1 | J21 interface |
| 4 | JST-XH 6-pin connectors | 3 | SPI cable connectors |
| 5 | 4.7 kOhm 1/4W resistor | 2 | MISO divider (series) |
| 6 | 10 kOhm 1/4W resistor | 2 | MISO divider (pull-down) + CS2 pull-up |
| 7 | NEMA17 stepper motor (42BYG) | 2 | Bench test motors |
| 8 | 12 V / 3 A bench power supply | 1 | VMOT for all drivers |
| 9 | 4-pin motor cable (JST-PH) | 4 | Motor connections |
| 10 | Dupont jumper wires (M-F, 20 cm) | 1 pack | Inter-board wiring |

---

## 9. Architecture Corrections Required

The following documents contain errors that must be fixed as part of this work:

1. **`docs/architecture/motor-control-architecture.md` Section 5.2**:
   - Current text assumes 40-bit datagrams for all 4 drivers (160-bit chain)
   - TMC260C actually uses 20-bit datagrams
   - Fix: replace daisy-chain description with split CS topology
   - Add note about datagram size per driver type

2. **`docs/hardware/adapter-board-spec.md`**:
   - Daisy-chain frame calculation needs update for mixed 20-bit/40-bit drivers
   - Production board should also use split CS (or separate SPI buses)

---

## 10. Risk and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| NTB0104 C_load exceeded (J21 on-board shifter) | SPI signal integrity failure | Keep trace length short, verify with oscilloscope at S1 |
| TXS0108E auto-direction latch-up | Signal stuck high/low | Add 100 nF decoupling cap on VA/VB, power sequence VA before VB |
| Python spidev STEP pulse jitter | Inconsistent motor speed | Acceptable for bench test (<1 kHz); production uses M7 GPT ISR |
| Shared DIR line limits concurrent motion | Cannot run FEED+BEND in true parallel | S5 uses sequential Feed-then-Bend per B-code step (matches production) |
| TMC5072-BOB VS max 26 V | Cannot test at higher voltages | 12 V bench PSU is within spec for all three boards |
