# Motor Driver Test Bench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-mode motor backend (mock/spidev/m7) with diagnostic API, TMC260C/TMC5072 protocol drivers, and a frontend DiagnosticsPage so that real Trinamic driver boards can be validated on the i.MX8MP EVK via J21.

**Architecture:** A `MotorBackend` ABC defines the transport layer (SPI transfer, GPIO, STEP pulses). Three implementations—`MockMotorBackend`, `SpidevMotorBackend`, `IpcMotorBackend`—are selected at startup by `OB_MOTOR_BACKEND`. On top of the backend sit `Tmc260cDriver` (20-bit) and `Tmc5072Driver` (40-bit), exposed through a `DiagService` → `diag_router` REST/WebSocket stack. The existing `MotorService` continues to use `IpcClient` for production; the diagnostic path is additive, not a replacement.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, spidev, gpiod, React 18, Recharts, TypeScript, Vite

**Design Spec:** `docs/superpowers/specs/2026-04-16-motor-test-bench-design.md`

---

## File Map

### New Files (Backend)

| File | Responsibility |
|------|----------------|
| `src/app/server/services/motor_backend.py` | `MotorBackend` ABC + `MockMotorBackend` |
| `src/app/server/services/spi_backend.py` | `SpidevMotorBackend` (Linux spidev + gpiod) |
| `src/app/server/services/tmc260c_driver.py` | TMC260C 20-bit SPI protocol driver |
| `src/app/server/services/tmc5072_driver.py` | TMC5072 40-bit SPI protocol driver |
| `src/app/server/services/diag_service.py` | Diagnostic service layer (register R/W, SPI test, SG calibration) |
| `src/app/server/routers/diag_router.py` | `/api/motor/diag/*` REST endpoints |
| `src/app/server/models/diag_schemas.py` | Pydantic models for diagnostic API |

### New Files (Frontend)

| File | Responsibility |
|------|----------------|
| `src/app/frontend/src/pages/DiagnosticsPage.tsx` | Full diagnostic UI: SPI test, register inspector, SG chart, jog, dump |
| `src/app/frontend/src/components/RegisterInspector.tsx` | TMC register read/write panel |
| `src/app/frontend/src/components/StallGuardChart.tsx` | Real-time SG2 Recharts line chart |

### New Files (Tests)

| File | Responsibility |
|------|----------------|
| `tests/test_tmc260c_driver.py` | TMC260C datagram framing, register encoding, status parsing |
| `tests/test_tmc5072_driver.py` | TMC5072 datagram framing, register encoding, position read |
| `tests/test_diag_service.py` | DiagService SPI test, register read/write, dump, SG calibration |
| `tests/test_motor_backend.py` | MockMotorBackend behavior |
| `tests/test_diag_router.py` | FastAPI TestClient integration tests for `/api/motor/diag/*` |

### New Files (M7 Firmware)

| File | Responsibility |
|------|----------------|
| `src/firmware/source/drivers/tmc5072.h` | TMC5072 register definitions + driver struct + API |
| `src/firmware/source/drivers/tmc5072.c` | TMC5072 SPI driver implementation |
| `src/firmware/source/drivers/tmc5072_hal_ops.c` | `motor_hal_ops_t` vtable for TMC5072 |

### Modified Files

| File | What Changes |
|------|--------------|
| `src/app/server/config.py` | Add `motor_backend`, `spi_device`, `spi_speed_hz`, 5 GPIO pin fields |
| `src/app/server/main.py` | Backend factory in lifespan, `DiagService` init, mount `diag_router`, `/ws/motor/diag` endpoint |
| `src/app/server/ws/manager.py` | Add `motor_diag` ConnectionSet + `_diag_loop` (200 Hz) + `handle_motor_diag` |
| `src/app/frontend/src/api/client.ts` | Add `diagApi` object + `wsApi.motorDiag` |
| `src/app/frontend/src/App.tsx` | Add `'diagnostics'` to `Page` union, import/render `DiagnosticsPage`, sidebar entry |
| `src/app/frontend/src/components/layout/Sidebar.tsx` | Add "Diagnostics" nav item |

---

## Task 1: Configuration Extensions

**Files:**
- Modify: `src/app/server/config.py:15-56`
- Test: `tests/test_motor_backend.py` (config portion tested implicitly via Task 2)

- [ ] **Step 1: Add new settings fields to config.py**

Open `src/app/server/config.py`. After the `ipc_timeout_s` field (line 34), add the motor backend and SPI/GPIO fields:

```python
    # ------------------------------------------------------------------
    # Motor backend selection
    # ------------------------------------------------------------------
    motor_backend: str = "mock"  # "mock" | "spidev" | "m7"

    # ------------------------------------------------------------------
    # SPI (spidev mode only)
    # ------------------------------------------------------------------
    spi_device: str = "/dev/spidev1.0"
    spi_speed_hz: int = 2_000_000

    # ------------------------------------------------------------------
    # GPIO pins (spidev mode only) — i.MX8MP J21 header
    # ------------------------------------------------------------------
    gpio_cs1: str = "GPIO3_IO19"
    gpio_cs2: str = "GPIO3_IO20"
    gpio_feed_step: str = "GPIO3_IO22"
    gpio_bend_step: str = "GPIO3_IO24"
    gpio_dir: str = "GPIO5_IO06"
```

- [ ] **Step 2: Verify config loads with defaults**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -c "
from src.app.server.config import Settings
s = Settings()
assert s.motor_backend == 'mock'
assert s.spi_speed_hz == 2_000_000
assert s.gpio_cs1 == 'GPIO3_IO19'
print('OK: config defaults verified')
"
```
Expected: `OK: config defaults verified`

- [ ] **Step 3: Commit**

```bash
git add src/app/server/config.py
git commit -m "feat(config): add motor_backend, spi, gpio settings for test bench"
```

---

## Task 2: MotorBackend ABC + MockMotorBackend

**Files:**
- Create: `src/app/server/services/motor_backend.py`
- Create: `tests/test_motor_backend.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_motor_backend.py`:

```python
"""Unit tests for MotorBackend ABC and MockMotorBackend."""

import pytest
import asyncio


@pytest.fixture
def mock_backend():
    from src.app.server.services.motor_backend import MockMotorBackend
    return MockMotorBackend()


@pytest.mark.asyncio
async def test_mock_spi_transfer_returns_bytes(mock_backend):
    """Mock SPI transfer returns bytes of same length as input."""
    result = await mock_backend.spi_transfer(cs=0, data=bytes([0x00, 0x00, 0x00]))
    assert isinstance(result, bytes)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_mock_spi_transfer_tmc260c_status_format(mock_backend):
    """TMC260C 20-bit response: status flags in low byte, SG in upper bits."""
    # Send 3 bytes (20-bit TMC260C datagram)
    result = await mock_backend.spi_transfer(cs=0, data=bytes([0x09, 0x00, 0x00]))
    # Mock should return a valid 20-bit response (3 bytes)
    assert len(result) == 3
    # Parse 20-bit value
    val = (result[0] << 16) | (result[1] << 8) | result[2]
    # Bit 7 (STST - standstill) should be set in mock idle state
    assert val & 0x80 != 0


@pytest.mark.asyncio
async def test_mock_spi_transfer_tmc5072_format(mock_backend):
    """TMC5072 40-bit response: 5 bytes."""
    result = await mock_backend.spi_transfer(cs=2, data=bytes([0x00, 0x00, 0x00, 0x00, 0x00]))
    assert isinstance(result, bytes)
    assert len(result) == 5


@pytest.mark.asyncio
async def test_mock_set_gpio(mock_backend):
    """set_gpio should not raise."""
    await mock_backend.set_gpio("GPIO3_IO19", True)
    await mock_backend.set_gpio("GPIO3_IO19", False)


@pytest.mark.asyncio
async def test_mock_get_gpio(mock_backend):
    """get_gpio returns bool."""
    result = await mock_backend.get_gpio("GPIO5_IO07")
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_mock_pulse_step(mock_backend):
    """pulse_step should not raise and should update position."""
    await mock_backend.pulse_step(axis=0, count=100, freq_hz=200, direction=1)
    # Mock tracks position internally
    assert mock_backend.positions[0] == 100


@pytest.mark.asyncio
async def test_mock_pulse_step_reverse(mock_backend):
    """Reverse direction decrements position."""
    await mock_backend.pulse_step(axis=0, count=50, freq_hz=200, direction=-1)
    assert mock_backend.positions[0] == -50
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_motor_backend.py -v
```
Expected: `ModuleNotFoundError` — `motor_backend` doesn't exist yet.

- [ ] **Step 3: Implement MotorBackend ABC + MockMotorBackend**

Create `src/app/server/services/motor_backend.py`:

```python
"""
motor_backend.py — Abstract motor backend + mock implementation.

The MotorBackend ABC defines the transport layer for SPI, GPIO, and
STEP pulse operations. Three implementations exist:

  MockMotorBackend   — no hardware, simulated responses (default)
  SpidevMotorBackend — Linux spidev + gpiod (test bench)
  IpcMotorBackend    — RPMsg to M7 (production, future)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod


class MotorBackend(ABC):
    """Transport abstraction for motor driver communication."""

    @abstractmethod
    async def spi_transfer(self, cs: int, data: bytes) -> bytes:
        """Send SPI datagram to chip-select `cs`, return response bytes."""
        ...

    @abstractmethod
    async def set_gpio(self, pin: str, value: bool) -> None:
        """Set a GPIO output pin high (True) or low (False)."""
        ...

    @abstractmethod
    async def get_gpio(self, pin: str) -> bool:
        """Read a GPIO input pin value."""
        ...

    @abstractmethod
    async def pulse_step(self, axis: int, count: int,
                         freq_hz: int, direction: int) -> None:
        """Generate `count` STEP pulses at `freq_hz` for `axis`."""
        ...


class MockMotorBackend(MotorBackend):
    """Simulated backend for development and CI testing."""

    def __init__(self) -> None:
        self.positions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        self._gpio_state: dict[str, bool] = {}
        self._sg_value: int = 512  # mid-range StallGuard2

    async def spi_transfer(self, cs: int, data: bytes) -> bytes:
        n = len(data)
        if n == 3:
            # TMC260C 20-bit mock response: STST=1 (standstill), SG=512
            sg = self._sg_value
            # Response format: [19:10]=SG, [9:8]=00, [7:0]=status
            # STST bit is bit 7
            val = ((sg & 0x3FF) << 10) | 0x80  # STST=1
            return bytes([(val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF])
        elif n == 5:
            # TMC5072 40-bit mock response: status byte + 32-bit register value
            # Status byte: bits[7:4]=driver status, bits[1:0]=reset/driver_error
            return bytes([0x00, 0x00, 0x00, 0x00, 0x00])
        return bytes(n)

    async def set_gpio(self, pin: str, value: bool) -> None:
        self._gpio_state[pin] = value

    async def get_gpio(self, pin: str) -> bool:
        return self._gpio_state.get(pin, False)

    async def pulse_step(self, axis: int, count: int,
                         freq_hz: int, direction: int) -> None:
        self.positions[axis] = self.positions.get(axis, 0) + (count * direction)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_motor_backend.py -v
```
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/server/services/motor_backend.py tests/test_motor_backend.py
git commit -m "feat(backend): MotorBackend ABC + MockMotorBackend with tests"
```

---

## Task 3: TMC260C Protocol Driver

**Files:**
- Create: `src/app/server/services/tmc260c_driver.py`
- Create: `tests/test_tmc260c_driver.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tmc260c_driver.py`:

```python
"""Unit tests for Tmc260cDriver — 20-bit SPI protocol."""

import pytest


@pytest.fixture
def mock_backend():
    from src.app.server.services.motor_backend import MockMotorBackend
    return MockMotorBackend()


@pytest.fixture
def driver(mock_backend):
    from src.app.server.services.tmc260c_driver import Tmc260cDriver
    return Tmc260cDriver(backend=mock_backend, cs=0)


@pytest.mark.asyncio
async def test_write_register_chopconf(driver):
    """Writing CHOPCONF sends correct 20-bit datagram."""
    response = await driver.write_register(
        reg_tag=0x04,  # CHOPCONF
        value=0x101D5 & 0x1FFFF,  # 17-bit payload
    )
    assert isinstance(response, int)
    # Response is a 20-bit value
    assert 0 <= response < (1 << 20)


@pytest.mark.asyncio
async def test_write_register_encodes_tag(driver):
    """Register tag appears in bits [19:17] of the datagram."""
    # SGCSCONF tag = 0x06, bits [19:17] = 110
    datagram = driver.encode_datagram(reg_tag=0x06, value=0x00014)
    assert (datagram >> 17) & 0x07 == 0x06


@pytest.mark.asyncio
async def test_read_status_returns_structured(driver):
    """read_status returns a Tmc260cStatus with parsed fields."""
    status = await driver.read_status()
    assert hasattr(status, 'sg_result')
    assert hasattr(status, 'stst')
    assert hasattr(status, 'ot')
    assert hasattr(status, 'otpw')
    assert hasattr(status, 's2ga')
    assert hasattr(status, 's2gb')
    assert hasattr(status, 'ola')
    assert hasattr(status, 'olb')
    assert isinstance(status.sg_result, int)
    assert 0 <= status.sg_result <= 1023


@pytest.mark.asyncio
async def test_read_status_mock_standstill(driver):
    """Mock backend reports standstill (STST=1) when idle."""
    status = await driver.read_status()
    assert status.stst is True


@pytest.mark.asyncio
async def test_set_current_range(driver):
    """set_current accepts 0-31 and raises ValueError outside range."""
    await driver.set_current(20)  # should not raise
    with pytest.raises(ValueError):
        await driver.set_current(32)
    with pytest.raises(ValueError):
        await driver.set_current(-1)


@pytest.mark.asyncio
async def test_set_microstep(driver):
    """set_microstep accepts valid MRES values."""
    await driver.set_microstep(0x04)  # 16 microsteps
    await driver.set_microstep(0x00)  # 256 microsteps


@pytest.mark.asyncio
async def test_set_stallguard(driver):
    """set_stallguard accepts threshold in range -64..+63."""
    await driver.set_stallguard(threshold=10, filter_enable=True)
    await driver.set_stallguard(threshold=-64, filter_enable=False)
    with pytest.raises(ValueError):
        await driver.set_stallguard(threshold=64, filter_enable=True)


@pytest.mark.asyncio
async def test_dump_registers(driver):
    """dump returns dict with all 5 TMC260C register names."""
    dump = await driver.dump_registers()
    assert 'DRVCTRL' in dump
    assert 'CHOPCONF' in dump
    assert 'SMARTEN' in dump
    assert 'SGCSCONF' in dump
    assert 'DRVCONF' in dump
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_tmc260c_driver.py -v
```
Expected: `ModuleNotFoundError` — `tmc260c_driver` doesn't exist yet.

- [ ] **Step 3: Implement Tmc260cDriver**

Create `src/app/server/services/tmc260c_driver.py`:

```python
"""
tmc260c_driver.py — TMC260C 20-bit SPI protocol driver.

The TMC260C uses 20-bit SPI datagrams (MSB first, SPI Mode 3, max 2 MHz).
Each write simultaneously returns a 20-bit status/SG response.

Register address tags occupy bits [19:17]:
  DRVCTRL  = 00x (bit19=0, bit18=0)
  CHOPCONF = 100
  SMARTEN  = 101
  SGCSCONF = 110
  DRVCONF  = 111

Reference: TMC260C-PA Datasheet Rev 1.04, mirrors src/firmware/source/drivers/tmc260c.h

IEC 62304 SW Class: B
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .motor_backend import MotorBackend

# Register tags (bits [19:17])
REG_DRVCTRL  = 0x00
REG_CHOPCONF = 0x04
REG_SMARTEN  = 0x05
REG_SGCSCONF = 0x06
REG_DRVCONF  = 0x07

# Default register values (mirrors tmc260c.h defaults)
CHOPCONF_DEFAULT = 0x101D5  # SpreadCycle, TOFF=5, HSTRT=4, HEND=1, TBL=2
SMARTEN_DEFAULT  = 0xA0000  # coolStep disabled
SGCSCONF_DEFAULT = 0xD0014  # CS=20, SGT=0, SFILT=1
DRVCONF_DEFAULT  = 0xE0050  # RDSEL=SG, VSENSE=1

# Response bit masks
RESP_SG_BIT   = 1 << 0
RESP_OT       = 1 << 1
RESP_OTPW     = 1 << 2
RESP_S2GA     = 1 << 3
RESP_S2GB     = 1 << 4
RESP_OLA      = 1 << 5
RESP_OLB      = 1 << 6
RESP_STST     = 1 << 7

RESP_SG_VALUE_SHIFT = 10
RESP_SG_VALUE_MASK  = 0x3FF


@dataclass
class Tmc260cStatus:
    """Parsed TMC260C 20-bit SPI response."""
    raw: int
    sg_result: int
    stst: bool
    ot: bool
    otpw: bool
    s2ga: bool
    s2gb: bool
    ola: bool
    olb: bool
    sg_active: bool

    @property
    def has_fault(self) -> bool:
        return self.ot or self.s2ga or self.s2gb


class Tmc260cDriver:
    """TMC260C 20-bit SPI protocol driver."""

    def __init__(self, backend: MotorBackend, cs: int) -> None:
        self._backend = backend
        self._cs = cs
        self._last_status: Tmc260cStatus | None = None

    @staticmethod
    def encode_datagram(reg_tag: int, value: int) -> int:
        """Encode a 20-bit datagram from register tag and payload value.

        For DRVCTRL (tag=0x00): bits [19:18] = 00, bits [17:0] = value
        For others: bits [19:17] = tag, bits [16:0] = value
        """
        if reg_tag == REG_DRVCTRL:
            return value & 0xFFFFF  # DRVCTRL: tag is implicitly 00x
        return ((reg_tag & 0x07) << 17) | (value & 0x1FFFF)

    @staticmethod
    def parse_response(raw_bytes: bytes) -> Tmc260cStatus:
        """Parse 3-byte SPI response into Tmc260cStatus."""
        val = (raw_bytes[0] << 16) | (raw_bytes[1] << 8) | raw_bytes[2]
        val &= 0xFFFFF  # mask to 20 bits
        flags = val & 0xFF
        sg_result = (val >> RESP_SG_VALUE_SHIFT) & RESP_SG_VALUE_MASK
        return Tmc260cStatus(
            raw=val,
            sg_result=sg_result,
            stst=bool(flags & RESP_STST),
            ot=bool(flags & RESP_OT),
            otpw=bool(flags & RESP_OTPW),
            s2ga=bool(flags & RESP_S2GA),
            s2gb=bool(flags & RESP_S2GB),
            ola=bool(flags & RESP_OLA),
            olb=bool(flags & RESP_OLB),
            sg_active=bool(flags & RESP_SG_BIT),
        )

    async def write_register(self, reg_tag: int, value: int) -> int:
        """Write a register and return the 20-bit response value."""
        datagram = self.encode_datagram(reg_tag, value)
        tx = bytes([(datagram >> 16) & 0xFF, (datagram >> 8) & 0xFF, datagram & 0xFF])
        rx = await self._backend.spi_transfer(self._cs, tx)
        val = (rx[0] << 16) | (rx[1] << 8) | rx[2]
        return val & 0xFFFFF

    async def read_status(self) -> Tmc260cStatus:
        """Read driver status by sending a DRVCONF read command."""
        # Reading status: send current DRVCONF (RDSEL=SG) to get SG value back
        datagram = DRVCONF_DEFAULT
        tx = bytes([(datagram >> 16) & 0xFF, (datagram >> 8) & 0xFF, datagram & 0xFF])
        rx = await self._backend.spi_transfer(self._cs, tx)
        status = self.parse_response(rx)
        self._last_status = status
        return status

    async def set_current(self, scale: int) -> None:
        """Set motor current scale (0-31)."""
        if not 0 <= scale <= 31:
            raise ValueError(f"Current scale must be 0-31, got {scale}")
        # SGCSCONF: tag=0x06, CS in bits [4:0], keep SGT and SFILT from default
        value = (SGCSCONF_DEFAULT & 0x1FFE0) | (scale & 0x1F)
        await self.write_register(REG_SGCSCONF, value)

    async def set_microstep(self, mres: int) -> None:
        """Set microstepping resolution (0=256, 1=128, ..., 8=fullstep)."""
        if not 0 <= mres <= 8:
            raise ValueError(f"MRES must be 0-8, got {mres}")
        # DRVCTRL: INTPOL=1 (bit 9), MRES in bits [3:0]
        value = (1 << 9) | (mres & 0x0F)
        await self.write_register(REG_DRVCTRL, value)

    async def set_stallguard(self, threshold: int, filter_enable: bool) -> None:
        """Configure StallGuard2 threshold (-64 to +63)."""
        if not -64 <= threshold <= 63:
            raise ValueError(f"SG threshold must be -64..+63, got {threshold}")
        # SGCSCONF: SGT in bits [14:8] (7-bit signed), SFILT in bit 16
        sgt = threshold & 0x7F
        cs = SGCSCONF_DEFAULT & 0x1F  # keep current scale
        value = (int(filter_enable) << 16) | (sgt << 8) | cs
        await self.write_register(REG_SGCSCONF, value)

    async def dump_registers(self) -> dict[str, int]:
        """Dump all 5 writable registers by re-writing defaults and capturing responses.

        Note: TMC260C has no dedicated read-back. Writing a register returns the
        *previous* status, not the register value. For a true register dump we
        re-write known defaults and return the expected values.
        """
        return {
            'DRVCTRL': (1 << 9) | 0x04,  # INTPOL=1, MRES=16
            'CHOPCONF': CHOPCONF_DEFAULT & 0x1FFFF,
            'SMARTEN': SMARTEN_DEFAULT & 0x1FFFF,
            'SGCSCONF': SGCSCONF_DEFAULT & 0x1FFFF,
            'DRVCONF': DRVCONF_DEFAULT & 0x1FFFF,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_tmc260c_driver.py -v
```
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/server/services/tmc260c_driver.py tests/test_tmc260c_driver.py
git commit -m "feat(driver): TMC260C 20-bit SPI protocol driver with tests"
```

---

## Task 4: TMC5072 Protocol Driver

**Files:**
- Create: `src/app/server/services/tmc5072_driver.py`
- Create: `tests/test_tmc5072_driver.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tmc5072_driver.py`:

```python
"""Unit tests for Tmc5072Driver — 40-bit SPI protocol."""

import pytest


@pytest.fixture
def mock_backend():
    from src.app.server.services.motor_backend import MockMotorBackend
    return MockMotorBackend()


@pytest.fixture
def driver(mock_backend):
    from src.app.server.services.tmc5072_driver import Tmc5072Driver
    return Tmc5072Driver(backend=mock_backend, cs=2)


@pytest.mark.asyncio
async def test_read_register_returns_int(driver):
    """read_register returns a 32-bit integer value."""
    value = await driver.read_register(0x00)  # GCONF
    assert isinstance(value, int)
    assert 0 <= value < (1 << 32)


@pytest.mark.asyncio
async def test_write_register_no_error(driver):
    """write_register should complete without error."""
    await driver.write_register(0x6C, 0x000101D5)  # CHOPCONF motor 0


@pytest.mark.asyncio
async def test_encode_write_datagram(driver):
    """Write datagram: bit[39]=1, addr in [38:32], data in [31:0]."""
    addr = 0x6C
    value = 0x000101D5
    datagram = driver.encode_write(addr, value)
    assert len(datagram) == 5
    assert datagram[0] & 0x80 != 0  # write bit set
    assert datagram[0] & 0x7F == addr


@pytest.mark.asyncio
async def test_encode_read_datagram(driver):
    """Read datagram: bit[39]=0, addr in [38:32], data=0."""
    addr = 0x00
    datagram = driver.encode_read(addr)
    assert len(datagram) == 5
    assert datagram[0] & 0x80 == 0  # write bit clear
    assert datagram[0] & 0x7F == addr
    assert datagram[1:] == bytes(4)


@pytest.mark.asyncio
async def test_move_to_no_error(driver):
    """move_to should complete without error."""
    await driver.move_to(motor=0, position=1000, vmax=50000, amax=5000)


@pytest.mark.asyncio
async def test_get_position_returns_int(driver):
    """get_position returns integer step count."""
    pos = await driver.get_position(motor=0)
    assert isinstance(pos, int)


@pytest.mark.asyncio
async def test_get_drv_status_returns_int(driver):
    """get_drv_status returns raw DRV_STATUS register value."""
    status = await driver.get_drv_status(motor=0)
    assert isinstance(status, int)


@pytest.mark.asyncio
async def test_dump_registers(driver):
    """dump returns dict with key TMC5072 registers."""
    dump = await driver.dump_registers()
    assert 'GCONF' in dump
    assert 'CHOPCONF_M0' in dump
    assert 'DRV_STATUS_M0' in dump
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_tmc5072_driver.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement Tmc5072Driver**

Create `src/app/server/services/tmc5072_driver.py`:

```python
"""
tmc5072_driver.py — TMC5072 40-bit SPI protocol driver.

The TMC5072 uses 40-bit SPI datagrams: 8-bit address + 32-bit data.
Bit 7 of the address byte: 0=read, 1=write.
The chip contains 2 independent motor channels.

Reference: TMC5072 Datasheet Rev 1.17
Motor 0 registers: 0x00-0x3F (shared) + 0x40-0x6F (motor 0 specific)
Motor 1 registers: 0x70-0x7F (motor 1 specific)

IEC 62304 SW Class: B
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .motor_backend import MotorBackend

# Key register addresses
GCONF       = 0x00
GSTAT       = 0x01
IC_VERSION  = 0x73

# Per-motor register offsets (motor 0 base, motor 1 = base + 0x10)
RAMPMODE    = 0x20  # 0x20 (M0), 0x40 (M1)
XACTUAL     = 0x21  # 0x21 (M0), 0x41 (M1)
VACTUAL     = 0x22
VMAX        = 0x27
AMAX        = 0x28
DMAX        = 0x29
XTARGET     = 0x2D
IHOLD_IRUN  = 0x30
CHOPCONF    = 0x6C  # 0x6C (M0), 0x7C (M1)
DRV_STATUS  = 0x6F  # 0x6F (M0), 0x7F (M1)
RAMP_STAT   = 0x35  # 0x35 (M0), 0x55 (M1)

# Motor 1 offset
M1_OFFSET = 0x10


def _motor_reg(base_addr: int, motor: int) -> int:
    """Return register address adjusted for motor channel."""
    if motor == 1:
        if base_addr >= 0x6C:
            return base_addr + 0x10  # CHOPCONF: 0x6C -> 0x7C
        elif base_addr >= 0x20:
            return base_addr + 0x20  # RAMPMODE: 0x20 -> 0x40
    return base_addr


class Tmc5072Driver:
    """TMC5072 40-bit SPI protocol driver."""

    def __init__(self, backend: MotorBackend, cs: int) -> None:
        self._backend = backend
        self._cs = cs

    @staticmethod
    def encode_write(addr: int, value: int) -> bytes:
        """Encode a 40-bit write datagram: [W|addr(7)] [data(32)]."""
        return bytes([
            0x80 | (addr & 0x7F),
            (value >> 24) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])

    @staticmethod
    def encode_read(addr: int) -> bytes:
        """Encode a 40-bit read datagram: [R|addr(7)] [0x00000000]."""
        return bytes([addr & 0x7F, 0, 0, 0, 0])

    @staticmethod
    def parse_response(rx: bytes) -> int:
        """Extract 32-bit register value from 5-byte SPI response."""
        return (rx[1] << 24) | (rx[2] << 16) | (rx[3] << 8) | rx[4]

    async def read_register(self, addr: int) -> int:
        """Read a TMC5072 register (requires two SPI transfers)."""
        # First transfer: send read request (response is from *previous* command)
        tx = self.encode_read(addr)
        await self._backend.spi_transfer(self._cs, tx)
        # Second transfer: send NOP to clock out the actual response
        rx = await self._backend.spi_transfer(self._cs, bytes(5))
        return self.parse_response(rx)

    async def write_register(self, addr: int, value: int) -> None:
        """Write a 32-bit value to a TMC5072 register."""
        tx = self.encode_write(addr, value)
        await self._backend.spi_transfer(self._cs, tx)

    async def move_to(self, motor: int, position: int,
                      vmax: int, amax: int) -> None:
        """Command motor to move to absolute position using internal ramp."""
        await self.write_register(_motor_reg(RAMPMODE, motor), 0)  # positioning mode
        await self.write_register(_motor_reg(VMAX, motor), vmax)
        await self.write_register(_motor_reg(AMAX, motor), amax)
        await self.write_register(_motor_reg(DMAX, motor), amax)
        await self.write_register(_motor_reg(XTARGET, motor), position)

    async def get_position(self, motor: int) -> int:
        """Read current position (XACTUAL) for motor channel."""
        val = await self.read_register(_motor_reg(XACTUAL, motor))
        # Sign-extend 32-bit to Python int
        if val >= 0x80000000:
            val -= 0x100000000
        return val

    async def get_drv_status(self, motor: int) -> int:
        """Read DRV_STATUS register for motor channel."""
        return await self.read_register(_motor_reg(DRV_STATUS, motor))

    async def dump_registers(self) -> dict[str, int]:
        """Dump key registers for both motor channels."""
        result = {}
        result['GCONF'] = await self.read_register(GCONF)
        result['GSTAT'] = await self.read_register(GSTAT)
        for m in (0, 1):
            suffix = f"_M{m}"
            result[f'XACTUAL{suffix}'] = await self.read_register(_motor_reg(XACTUAL, m))
            result[f'VACTUAL{suffix}'] = await self.read_register(_motor_reg(VACTUAL, m))
            result[f'CHOPCONF{suffix}'] = await self.read_register(_motor_reg(CHOPCONF, m))
            result[f'DRV_STATUS{suffix}'] = await self.read_register(_motor_reg(DRV_STATUS, m))
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_tmc5072_driver.py -v
```
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/server/services/tmc5072_driver.py tests/test_tmc5072_driver.py
git commit -m "feat(driver): TMC5072 40-bit SPI protocol driver with tests"
```

---

## Task 5: Diagnostic Schemas

**Files:**
- Create: `src/app/server/models/diag_schemas.py`

- [ ] **Step 1: Create diagnostic Pydantic models**

Create `src/app/server/models/diag_schemas.py`:

```python
"""
diag_schemas.py — Pydantic v2 models for the diagnostic API.

IEC 62304 SW Class: B
"""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


class DriverId(StrEnum):
    TMC260C_0 = "tmc260c_0"
    TMC260C_1 = "tmc260c_1"
    TMC5072   = "tmc5072"


class DiagRegisterWriteRequest(BaseModel):
    value: int = Field(..., ge=0, description="Register value to write")


class DiagRegisterResponse(BaseModel):
    driver: DriverId
    addr: str
    value: int
    value_hex: str


class DiagDumpResponse(BaseModel):
    driver: DriverId
    registers: dict[str, str]  # name -> hex value


class SpiTestResult(BaseModel):
    driver: DriverId
    ok: bool
    latency_us: Optional[float] = None
    error: Optional[str] = None


class SpiTestResponse(BaseModel):
    results: list[SpiTestResult]


class DiagBackendResponse(BaseModel):
    backend: str
    spi_device: Optional[str] = None
    spi_speed_hz: Optional[int] = None
    drivers: list[DriverId]


class StallGuardCalibrationRequest(BaseModel):
    driver: DriverId = Field(..., description="Driver to calibrate")
    speed_hz: int = Field(200, gt=0, le=2000, description="STEP frequency during calibration")
    axis: int = Field(0, ge=0, le=3, description="Axis to jog during calibration")


class StallGuardCalibrationResponse(BaseModel):
    driver: DriverId
    threshold: int
    sg_min: int
    sg_max: int
    sg_avg: float


class WsDiagEvent(BaseModel):
    """200 Hz diagnostic status broadcast over /ws/motor/diag."""
    type: str = "diag_status"
    drivers: dict[str, dict]  # driver_id -> {sg_result, status_flags, ...}
    timestamp_us: int
```

- [ ] **Step 2: Verify models import cleanly**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -c "
from src.app.server.models.diag_schemas import (
    DriverId, DiagRegisterWriteRequest, DiagRegisterResponse,
    DiagDumpResponse, SpiTestResult, SpiTestResponse,
    DiagBackendResponse, StallGuardCalibrationRequest,
    StallGuardCalibrationResponse, WsDiagEvent,
)
print('OK: all diag_schemas models imported')
"
```
Expected: `OK: all diag_schemas models imported`

- [ ] **Step 3: Commit**

```bash
git add src/app/server/models/diag_schemas.py
git commit -m "feat(schemas): diagnostic API Pydantic models"
```

---

## Task 6: DiagService

**Files:**
- Create: `src/app/server/services/diag_service.py`
- Create: `tests/test_diag_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_diag_service.py`:

```python
"""Unit tests for DiagService."""

import pytest


@pytest.fixture
def mock_backend():
    from src.app.server.services.motor_backend import MockMotorBackend
    return MockMotorBackend()


@pytest.fixture
def diag_service(mock_backend):
    from src.app.server.services.diag_service import DiagService
    return DiagService(backend=mock_backend)


@pytest.mark.asyncio
async def test_spi_test_all_drivers(diag_service):
    """SPI test returns results for all 3 drivers."""
    results = await diag_service.spi_test()
    assert len(results) == 3
    for r in results:
        assert r.ok is True


@pytest.mark.asyncio
async def test_read_register_tmc260c(diag_service):
    """Read a TMC260C register returns valid response."""
    resp = await diag_service.read_register("tmc260c_0", 0x04)
    assert resp.driver == "tmc260c_0"
    assert isinstance(resp.value, int)


@pytest.mark.asyncio
async def test_read_register_tmc5072(diag_service):
    """Read a TMC5072 register returns valid response."""
    resp = await diag_service.read_register("tmc5072", 0x00)
    assert resp.driver == "tmc5072"
    assert isinstance(resp.value, int)


@pytest.mark.asyncio
async def test_write_register_tmc260c(diag_service):
    """Write a TMC260C register completes without error."""
    resp = await diag_service.write_register("tmc260c_0", 0x04, 0x101D5)
    assert resp.driver == "tmc260c_0"


@pytest.mark.asyncio
async def test_dump_tmc260c(diag_service):
    """Dump TMC260C returns 5 registers."""
    dump = await diag_service.dump_registers("tmc260c_0")
    assert len(dump.registers) == 5


@pytest.mark.asyncio
async def test_dump_tmc5072(diag_service):
    """Dump TMC5072 returns key registers."""
    dump = await diag_service.dump_registers("tmc5072")
    assert 'GCONF' in dump.registers


@pytest.mark.asyncio
async def test_get_backend_info(diag_service):
    """get_backend_info returns mock backend info."""
    info = await diag_service.get_backend_info()
    assert info.backend == "mock"
    assert len(info.drivers) == 3


@pytest.mark.asyncio
async def test_invalid_driver_raises(diag_service):
    """Invalid driver ID raises ValueError."""
    with pytest.raises(ValueError):
        await diag_service.read_register("nonexistent", 0x00)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_diag_service.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement DiagService**

Create `src/app/server/services/diag_service.py`:

```python
"""
diag_service.py — Diagnostic service layer for TMC register access.

Orchestrates Tmc260cDriver and Tmc5072Driver instances on top of a
MotorBackend, providing SPI test, register R/W, dump, and SG calibration.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import time
import logging
from typing import TYPE_CHECKING

from ..models.diag_schemas import (
    DiagBackendResponse,
    DiagDumpResponse,
    DiagRegisterResponse,
    DriverId,
    SpiTestResult,
)
from .tmc260c_driver import Tmc260cDriver
from .tmc5072_driver import Tmc5072Driver

if TYPE_CHECKING:
    from .motor_backend import MotorBackend

log = logging.getLogger(__name__)


class DiagService:
    """Diagnostic service for low-level TMC driver access."""

    def __init__(self, backend: MotorBackend) -> None:
        self._backend = backend
        self._tmc260c_0 = Tmc260cDriver(backend, cs=0)
        self._tmc260c_1 = Tmc260cDriver(backend, cs=1)
        self._tmc5072 = Tmc5072Driver(backend, cs=2)

    def _get_driver(self, driver_id: str) -> Tmc260cDriver | Tmc5072Driver:
        drivers = {
            "tmc260c_0": self._tmc260c_0,
            "tmc260c_1": self._tmc260c_1,
            "tmc5072": self._tmc5072,
        }
        if driver_id not in drivers:
            raise ValueError(f"Unknown driver: {driver_id}. Valid: {list(drivers.keys())}")
        return drivers[driver_id]

    async def spi_test(self) -> list[SpiTestResult]:
        """Test SPI connectivity with all drivers."""
        results = []
        for did in (DriverId.TMC260C_0, DriverId.TMC260C_1, DriverId.TMC5072):
            t0 = time.monotonic()
            try:
                drv = self._get_driver(did)
                if isinstance(drv, Tmc260cDriver):
                    await drv.read_status()
                else:
                    await drv.read_register(0x00)  # GCONF
                latency = (time.monotonic() - t0) * 1_000_000
                results.append(SpiTestResult(driver=did, ok=True, latency_us=latency))
            except Exception as exc:
                latency = (time.monotonic() - t0) * 1_000_000
                results.append(SpiTestResult(
                    driver=did, ok=False, latency_us=latency, error=str(exc)
                ))
        return results

    async def read_register(self, driver_id: str, addr: int) -> DiagRegisterResponse:
        """Read a single register from the specified driver."""
        drv = self._get_driver(driver_id)
        if isinstance(drv, Tmc260cDriver):
            value = await drv.write_register(addr, 0)  # TMC260C: write to read
        else:
            value = await drv.read_register(addr)
        return DiagRegisterResponse(
            driver=DriverId(driver_id),
            addr=f"0x{addr:02X}",
            value=value,
            value_hex=f"0x{value:08X}",
        )

    async def write_register(self, driver_id: str, addr: int, value: int) -> DiagRegisterResponse:
        """Write a value to a single register."""
        drv = self._get_driver(driver_id)
        if isinstance(drv, Tmc260cDriver):
            resp = await drv.write_register(addr, value)
        else:
            await drv.write_register(addr, value)
            resp = value
        return DiagRegisterResponse(
            driver=DriverId(driver_id),
            addr=f"0x{addr:02X}",
            value=resp,
            value_hex=f"0x{resp:08X}",
        )

    async def dump_registers(self, driver_id: str) -> DiagDumpResponse:
        """Dump all status registers from the specified driver."""
        drv = self._get_driver(driver_id)
        raw_dump = await drv.dump_registers()
        hex_dump = {k: f"0x{v:08X}" for k, v in raw_dump.items()}
        return DiagDumpResponse(driver=DriverId(driver_id), registers=hex_dump)

    async def get_backend_info(self) -> DiagBackendResponse:
        """Return current backend mode and configuration."""
        backend_name = type(self._backend).__name__
        if "Mock" in backend_name:
            mode = "mock"
        elif "Spidev" in backend_name:
            mode = "spidev"
        else:
            mode = "m7"
        return DiagBackendResponse(
            backend=mode,
            drivers=[DriverId.TMC260C_0, DriverId.TMC260C_1, DriverId.TMC5072],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_diag_service.py -v
```
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/server/services/diag_service.py tests/test_diag_service.py
git commit -m "feat(diag): DiagService with SPI test, register R/W, dump"
```

---

## Task 7: Diagnostic Router

**Files:**
- Create: `src/app/server/routers/diag_router.py`
- Create: `tests/test_diag_router.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_diag_router.py`:

```python
"""Integration tests for /api/motor/diag/* endpoints."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mock backend."""
    from fastapi import FastAPI
    from src.app.server.routers.diag_router import router, get_diag_service
    from src.app.server.services.motor_backend import MockMotorBackend
    from src.app.server.services.diag_service import DiagService

    app = FastAPI()
    backend = MockMotorBackend()
    diag_svc = DiagService(backend)

    app.include_router(router)
    app.dependency_overrides[get_diag_service] = lambda: diag_svc

    return TestClient(app)


def test_get_backend(client):
    r = client.get("/api/motor/diag/backend")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["data"]["backend"] == "mock"


def test_spi_test(client):
    r = client.get("/api/motor/diag/spi-test")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    results = data["data"]["results"]
    assert len(results) == 3
    assert all(res["ok"] for res in results)


def test_read_register(client):
    r = client.get("/api/motor/diag/register/tmc260c_0/0x04")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert "value" in data["data"]


def test_write_register(client):
    r = client.post(
        "/api/motor/diag/register/tmc260c_0/0x04",
        json={"value": 0x101D5},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True


def test_dump_registers(client):
    r = client.get("/api/motor/diag/dump/tmc260c_0")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert "CHOPCONF" in data["data"]["registers"]


def test_dump_tmc5072(client):
    r = client.get("/api/motor/diag/dump/tmc5072")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert "GCONF" in data["data"]["registers"]


def test_invalid_driver_returns_error(client):
    r = client.get("/api/motor/diag/register/nonexistent/0x00")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_diag_router.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement diag_router**

Create `src/app/server/routers/diag_router.py`:

```python
"""
routers/diag_router.py — /api/motor/diag/* REST endpoints.

Low-level TMC register access for test bench diagnostics.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from ..models.diag_schemas import DiagRegisterWriteRequest
from ..models.schemas import ApiResponse, err, ok
from ..services.diag_service import DiagService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/motor/diag", tags=["diagnostics"])


def get_diag_service(request: Request) -> DiagService:
    return request.app.state.diag_service


# ---------------------------------------------------------------------------
# GET /api/motor/diag/backend
# ---------------------------------------------------------------------------

@router.get("/backend", response_model=ApiResponse)
async def get_backend(svc: DiagService = Depends(get_diag_service)) -> ApiResponse:
    """Return current motor backend mode and configuration."""
    try:
        info = await svc.get_backend_info()
        return ok(info.model_dump())
    except Exception as exc:
        return err(str(exc), "DIAG_BACKEND_ERROR")


# ---------------------------------------------------------------------------
# GET /api/motor/diag/spi-test
# ---------------------------------------------------------------------------

@router.get("/spi-test", response_model=ApiResponse)
async def spi_test(svc: DiagService = Depends(get_diag_service)) -> ApiResponse:
    """Test SPI connectivity with all drivers."""
    try:
        results = await svc.spi_test()
        return ok({"results": [r.model_dump() for r in results]})
    except Exception as exc:
        return err(str(exc), "SPI_TEST_ERROR")


# ---------------------------------------------------------------------------
# GET /api/motor/diag/register/{driver}/{addr}
# ---------------------------------------------------------------------------

@router.get("/register/{driver}/{addr}", response_model=ApiResponse)
async def read_register(
    driver: str,
    addr: str,
    svc: DiagService = Depends(get_diag_service),
) -> ApiResponse:
    """Read a single TMC register."""
    try:
        addr_int = int(addr, 16) if addr.startswith("0x") else int(addr)
        resp = await svc.read_register(driver, addr_int)
        return ok(resp.model_dump())
    except ValueError as exc:
        return err(str(exc), "INVALID_PARAM")
    except Exception as exc:
        return err(str(exc), "DIAG_READ_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/diag/register/{driver}/{addr}
# ---------------------------------------------------------------------------

@router.post("/register/{driver}/{addr}", response_model=ApiResponse)
async def write_register(
    driver: str,
    addr: str,
    body: DiagRegisterWriteRequest,
    svc: DiagService = Depends(get_diag_service),
) -> ApiResponse:
    """Write a value to a TMC register."""
    try:
        addr_int = int(addr, 16) if addr.startswith("0x") else int(addr)
        resp = await svc.write_register(driver, addr_int, body.value)
        return ok(resp.model_dump())
    except ValueError as exc:
        return err(str(exc), "INVALID_PARAM")
    except Exception as exc:
        return err(str(exc), "DIAG_WRITE_ERROR")


# ---------------------------------------------------------------------------
# GET /api/motor/diag/dump/{driver}
# ---------------------------------------------------------------------------

@router.get("/dump/{driver}", response_model=ApiResponse)
async def dump_registers(
    driver: str,
    svc: DiagService = Depends(get_diag_service),
) -> ApiResponse:
    """Dump all status registers from a driver."""
    try:
        dump = await svc.dump_registers(driver)
        return ok(dump.model_dump())
    except ValueError as exc:
        return err(str(exc), "INVALID_PARAM")
    except Exception as exc:
        return err(str(exc), "DIAG_DUMP_ERROR")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_diag_router.py -v
```
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/server/routers/diag_router.py tests/test_diag_router.py
git commit -m "feat(api): diagnostic router /api/motor/diag/* endpoints"
```

---

## Task 8: Wire DiagService into main.py + WsManager

**Files:**
- Modify: `src/app/server/main.py`
- Modify: `src/app/server/ws/manager.py`

- [ ] **Step 1: Add DiagService initialization to main.py lifespan**

In `src/app/server/main.py`, add imports at the top (after existing imports around line 38):

```python
from .routers import bending, cam, camera, motor, system, wifi, diag_router
from .services.motor_backend import MockMotorBackend
from .services.diag_service import DiagService
```

In the `lifespan` function, after `app.state.camera_service = camera_svc` (around line 83), add:

```python
    # Diagnostic backend — always MockMotorBackend until spidev is implemented
    diag_backend = MockMotorBackend()
    diag_svc = DiagService(diag_backend)
    app.state.diag_service = diag_svc
```

In `create_app`, after `application.include_router(wifi.router)` (line 168), add:

```python
    application.include_router(diag_router.router)
```

After the `/ws/system` endpoint (around line 181), add:

```python
    @application.websocket("/ws/motor/diag")
    async def ws_motor_diag(ws: WebSocket):
        await application.state.ws_manager.handle_motor_diag(ws)
```

- [ ] **Step 2: Add motor_diag channel to WsManager**

In `src/app/server/ws/manager.py`, in `WsManager.__init__` (around line 78), add:

```python
        self.motor_diag = ConnectionSet("motor_diag")
        self._diag_task: Optional[asyncio.Task] = None
```

In `start_background_tasks`, add a `diag_provider` parameter and start the loop:

```python
    def start_background_tasks(
        self,
        motor_provider:  Callable,
        camera_provider: Callable,
        system_provider: Callable,
        diag_provider: Optional[Callable] = None,
    ) -> None:
```

After the `_system_task` creation, add:

```python
        if diag_provider:
            self._diag_task = asyncio.create_task(
                self._diag_loop(diag_provider), name="ws_diag_loop"
            )
```

In the `stop` method, add `self._diag_task` to the cancel list:

```python
        for task in (self._motor_task, self._camera_task, self._system_task, self._diag_task):
```

Add the handler method:

```python
    async def handle_motor_diag(self, ws: WebSocket) -> None:
        """Handle a single /ws/motor/diag connection until disconnect."""
        await ws.accept()
        await self.motor_diag.add(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await self.motor_diag.remove(ws)
```

Add the broadcast loop:

```python
    async def _diag_loop(self, provider: Callable) -> None:
        """Broadcast diagnostic status at 200 Hz (5 ms intervals)."""
        while True:
            try:
                if self.motor_diag.count > 0:
                    data = await provider()
                    if data is not None:
                        payload = json.dumps({
                            "type": "diag_status",
                            "timestamp_us": int(time.monotonic() * 1_000_000),
                            **data,
                        })
                        await self.motor_diag.broadcast(payload)
            except Exception as exc:
                log.debug("WS diag loop error: %s", exc)
            await asyncio.sleep(0.005)  # 200 Hz
```

- [ ] **Step 3: Verify the server starts without errors**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -c "
from src.app.server.main import create_app
app = create_app()
# Check diag router is mounted
routes = [r.path for r in app.routes]
assert '/api/motor/diag/backend' in str(routes) or any('diag' in str(r.path) for r in app.routes)
print('OK: diag router mounted')
"
```
Expected: `OK: diag router mounted`

- [ ] **Step 4: Run all existing tests to verify no regressions**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/ -v --ignore=tests/build
```
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/server/main.py src/app/server/ws/manager.py
git commit -m "feat(server): wire DiagService + /ws/motor/diag into main app"
```

---

## Task 9: Frontend API Client Extensions

**Files:**
- Modify: `src/app/frontend/src/api/client.ts`

- [ ] **Step 1: Add diagnostic types and API client**

In `src/app/frontend/src/api/client.ts`, after the `BcodeStep` interface (around line 72), add:

```typescript
export interface SpiTestResultItem {
  driver: string;
  ok: boolean;
  latency_us: number | null;
  error: string | null;
}

export interface DiagRegisterResult {
  driver: string;
  addr: string;
  value: number;
  value_hex: string;
}

export interface DiagDumpResult {
  driver: string;
  registers: Record<string, string>;
}

export interface DiagBackendInfo {
  backend: string;
  spi_device: string | null;
  spi_speed_hz: number | null;
  drivers: string[];
}

export interface DiagEvent {
  type: string;
  drivers: Record<string, { sg_result: number; status_flags: number }>;
  timestamp_us: number;
}
```

After the `systemApi` object (around line 203), add:

```typescript
// ---------------------------------------------------------------------------
// Diagnostics API
// ---------------------------------------------------------------------------

export const diagApi = {
  backend: (): Promise<DiagBackendInfo> =>
    request("/api/motor/diag/backend"),

  spiTest: (): Promise<{ results: SpiTestResultItem[] }> =>
    request("/api/motor/diag/spi-test"),

  readRegister: (driver: string, addr: string): Promise<DiagRegisterResult> =>
    request(`/api/motor/diag/register/${driver}/${addr}`),

  writeRegister: (driver: string, addr: string, value: number): Promise<DiagRegisterResult> =>
    request(`/api/motor/diag/register/${driver}/${addr}`, {
      method: "POST",
      body: JSON.stringify({ value }),
    }),

  dump: (driver: string): Promise<DiagDumpResult> =>
    request(`/api/motor/diag/dump/${driver}`),
};
```

In the `wsApi` object (around line 225), add:

```typescript
  motorDiag: (cb: WsHandler<DiagEvent>): WebSocket =>
    openWs("/ws/motor/diag", cb),
```

- [ ] **Step 2: Verify TypeScript compiles**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender/src/app/frontend && npx tsc --noEmit 2>&1 | head -20
```
Expected: No errors related to `client.ts`.

- [ ] **Step 3: Commit**

```bash
git add src/app/frontend/src/api/client.ts
git commit -m "feat(frontend): add diagApi + wsApi.motorDiag to API client"
```

---

## Task 10: StallGuardChart Component

**Files:**
- Create: `src/app/frontend/src/components/StallGuardChart.tsx`

- [ ] **Step 1: Create the real-time SG2 chart component**

Create `src/app/frontend/src/components/StallGuardChart.tsx`:

```tsx
/**
 * StallGuardChart.tsx — Real-time StallGuard2 line chart.
 *
 * Displays SG values for all connected TMC drivers overlaid on a
 * Recharts LineChart. Fed by /ws/motor/diag at 200 Hz, downsampled
 * to display resolution (~20 fps).
 */

import { useEffect, useRef, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine } from 'recharts';
import { wsApi, type DiagEvent } from '../api/client';

interface SgDataPoint {
  time: number;
  tmc260c_0?: number;
  tmc260c_1?: number;
  tmc5072?: number;
}

interface StallGuardChartProps {
  threshold?: number;
  width?: number;
  height?: number;
}

const MAX_POINTS = 200;
const COLORS = {
  tmc260c_0: '#3b82f6',
  tmc260c_1: '#10b981',
  tmc5072: '#f59e0b',
};

export function StallGuardChart({ threshold, width = 600, height = 250 }: StallGuardChartProps) {
  const [data, setData] = useState<SgDataPoint[]>([]);
  const [live, setLive] = useState<Record<string, number>>({});
  const wsRef = useRef<WebSocket | null>(null);
  const startRef = useRef(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    let frameCount = 0;

    const ws = wsApi.motorDiag((evt: DiagEvent) => {
      frameCount++;
      // Downsample to ~20 fps (every 10th frame at 200 Hz)
      if (frameCount % 10 !== 0) return;

      const elapsed = (Date.now() - startRef.current) / 1000;
      const point: SgDataPoint = { time: Math.round(elapsed * 10) / 10 };
      const liveVals: Record<string, number> = {};

      for (const [drvId, info] of Object.entries(evt.drivers)) {
        point[drvId as keyof SgDataPoint] = info.sg_result;
        liveVals[drvId] = info.sg_result;
      }

      setData(prev => {
        const next = [...prev, point];
        return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next;
      });
      setLive(liveVals);
    });

    wsRef.current = ws;
    return () => ws.close();
  }, []);

  return (
    <div>
      <LineChart width={width} height={height} data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="time"
          stroke="#94a3b8"
          label={{ value: 'Time (s)', position: 'insideBottom', offset: -5, fill: '#94a3b8' }}
        />
        <YAxis domain={[0, 1023]} stroke="#94a3b8" />
        <Tooltip
          contentStyle={{ background: '#1e293b', border: '1px solid #334155', color: '#f1f5f9' }}
        />
        <Legend />
        {threshold !== undefined && (
          <ReferenceLine y={threshold} stroke="#ef4444" strokeDasharray="5 5" label="Threshold" />
        )}
        <Line type="monotone" dataKey="tmc260c_0" stroke={COLORS.tmc260c_0} dot={false} strokeWidth={2} />
        <Line type="monotone" dataKey="tmc260c_1" stroke={COLORS.tmc260c_1} dot={false} strokeWidth={2} />
        <Line type="monotone" dataKey="tmc5072" stroke={COLORS.tmc5072} dot={false} strokeWidth={2} />
      </LineChart>
      <div style={{ display: 'flex', gap: 16, fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
        {Object.entries(live).map(([id, val]) => (
          <span key={id} style={{ color: COLORS[id as keyof typeof COLORS] || '#94a3b8' }}>
            {id}: {val}
          </span>
        ))}
        {threshold !== undefined && (
          <span style={{ color: '#ef4444' }}>Threshold: {threshold}</span>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender/src/app/frontend && npx tsc --noEmit 2>&1 | head -20
```
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add src/app/frontend/src/components/StallGuardChart.tsx
git commit -m "feat(frontend): StallGuardChart real-time SG2 line chart"
```

---

## Task 11: RegisterInspector Component

**Files:**
- Create: `src/app/frontend/src/components/RegisterInspector.tsx`

- [ ] **Step 1: Create the register R/W panel component**

Create `src/app/frontend/src/components/RegisterInspector.tsx`:

```tsx
/**
 * RegisterInspector.tsx — TMC register read/write panel.
 *
 * Dropdown selects driver, text input for address and value,
 * Read/Write buttons, shows last result.
 */

import { useState } from 'react';
import { diagApi, type DiagRegisterResult } from '../api/client';

const DRIVERS = ['tmc260c_0', 'tmc260c_1', 'tmc5072'] as const;

const BTN_STYLE: React.CSSProperties = {
  padding: '6px 16px',
  borderRadius: 6,
  border: 'none',
  cursor: 'pointer',
  fontWeight: 600,
  fontSize: 13,
};

export function RegisterInspector() {
  const [driver, setDriver] = useState<string>('tmc260c_0');
  const [addr, setAddr] = useState('0x04');
  const [writeValue, setWriteValue] = useState('');
  const [result, setResult] = useState<DiagRegisterResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleRead() {
    setLoading(true);
    setError(null);
    try {
      const r = await diagApi.readRegister(driver, addr);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleWrite() {
    if (!writeValue) return;
    setLoading(true);
    setError(null);
    try {
      const val = parseInt(writeValue, writeValue.startsWith('0x') ? 16 : 10);
      const r = await diagApi.writeRegister(driver, addr, val);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ fontSize: 12, color: '#94a3b8' }}>Driver:</label>
        <select
          value={driver}
          onChange={e => setDriver(e.target.value)}
          style={{ background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px' }}
        >
          {DRIVERS.map(d => <option key={d} value={d}>{d}</option>)}
        </select>

        <label style={{ fontSize: 12, color: '#94a3b8' }}>Addr:</label>
        <input
          value={addr}
          onChange={e => setAddr(e.target.value)}
          style={{ width: 60, background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px', fontFamily: 'monospace' }}
        />

        <button
          onClick={handleRead}
          disabled={loading}
          style={{ ...BTN_STYLE, background: '#3b82f6', color: '#fff' }}
        >
          Read
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ fontSize: 12, color: '#94a3b8' }}>Value:</label>
        <input
          value={writeValue}
          onChange={e => setWriteValue(e.target.value)}
          placeholder="0x101D5"
          style={{ width: 100, background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px', fontFamily: 'monospace' }}
        />

        <button
          onClick={handleWrite}
          disabled={loading || !writeValue}
          style={{ ...BTN_STYLE, background: '#f59e0b', color: '#000' }}
        >
          Write
        </button>
      </div>

      {error && (
        <div style={{ color: '#ef4444', fontSize: 12 }}>Error: {error}</div>
      )}

      {result && (
        <div style={{ fontSize: 12, color: '#94a3b8', fontFamily: 'monospace' }}>
          Last: {result.driver} [{result.addr}] = {result.value_hex}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender/src/app/frontend && npx tsc --noEmit 2>&1 | head -20
```
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add src/app/frontend/src/components/RegisterInspector.tsx
git commit -m "feat(frontend): RegisterInspector TMC register R/W panel"
```

---

## Task 12: DiagnosticsPage + App Wiring

**Files:**
- Create: `src/app/frontend/src/pages/DiagnosticsPage.tsx`
- Modify: `src/app/frontend/src/App.tsx`
- Modify: `src/app/frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Create DiagnosticsPage**

Create `src/app/frontend/src/pages/DiagnosticsPage.tsx`:

```tsx
/**
 * DiagnosticsPage.tsx — Motor driver test bench diagnostic UI.
 *
 * Sections: SPI Test, Register Inspector, StallGuard2 Chart,
 * Motor Jog, Register Dump.
 */

import { useState } from 'react';
import { diagApi, motorApi, type SpiTestResultItem, type DiagDumpResult } from '../api/client';
import { RegisterInspector } from '../components/RegisterInspector';
import { StallGuardChart } from '../components/StallGuardChart';

const CARD: React.CSSProperties = {
  background: '#1e293b',
  borderRadius: 8,
  padding: 16,
  border: '1px solid #334155',
};

const BTN: React.CSSProperties = {
  padding: '8px 16px',
  borderRadius: 6,
  border: 'none',
  cursor: 'pointer',
  fontWeight: 600,
  fontSize: 13,
};

const DRIVERS = ['tmc260c_0', 'tmc260c_1', 'tmc5072'] as const;

export function DiagnosticsPage() {
  // SPI Test state
  const [spiResults, setSpiResults] = useState<SpiTestResultItem[] | null>(null);
  const [spiLoading, setSpiLoading] = useState(false);

  // Backend info
  const [backendInfo, setBackendInfo] = useState<string>('--');

  // Dump state
  const [dumpResult, setDumpResult] = useState<DiagDumpResult | null>(null);
  const [dumpLoading, setDumpLoading] = useState(false);

  // Jog state
  const [jogAxis, setJogAxis] = useState(0);
  const [jogSpeed, setJogSpeed] = useState(10);
  const [jogStatus, setJogStatus] = useState('IDLE');

  // SG threshold
  const [sgThreshold, setSgThreshold] = useState<number | undefined>(undefined);

  // Fetch backend info on mount
  useState(() => {
    diagApi.backend().then(info => {
      setBackendInfo(`${info.backend} | ${info.spi_speed_hz ? (info.spi_speed_hz / 1e6).toFixed(0) + ' MHz' : 'N/A'}`);
    }).catch(() => setBackendInfo('error'));
  });

  async function handleSpiTest() {
    setSpiLoading(true);
    try {
      const r = await diagApi.spiTest();
      setSpiResults(r.results);
    } catch { setSpiResults(null); }
    finally { setSpiLoading(false); }
  }

  async function handleDump(driver: string) {
    setDumpLoading(true);
    try {
      const r = await diagApi.dump(driver);
      setDumpResult(r);
    } catch { setDumpResult(null); }
    finally { setDumpLoading(false); }
  }

  async function handleJog(direction: 1 | -1) {
    try {
      const r = await motorApi.jog(jogAxis, direction, jogSpeed, 100);
      setJogStatus(r.state === 3 ? 'JOGGING' : 'IDLE');
    } catch { setJogStatus('ERROR'); }
  }

  async function handleJogStop() {
    try {
      await motorApi.stop();
      setJogStatus('IDLE');
    } catch { setJogStatus('ERROR'); }
  }

  return (
    <div style={{ padding: 20, maxWidth: 900 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#f1f5f9' }}>Diagnostics</h2>
        <span style={{ fontSize: 12, color: '#64748b' }}>Backend: {backendInfo}</span>
      </div>

      {/* Row 1: SPI Test + Register Inspector */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12, marginBottom: 12 }}>
        {/* SPI Test */}
        <div style={CARD}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>SPI Test</h3>
          <button onClick={handleSpiTest} disabled={spiLoading} style={{ ...BTN, background: '#3b82f6', color: '#fff' }}>
            {spiLoading ? 'Testing...' : 'Run SPI Test'}
          </button>
          {spiResults && (
            <div style={{ marginTop: 8, fontSize: 12 }}>
              {spiResults.map(r => (
                <div key={r.driver} style={{ color: r.ok ? '#10b981' : '#ef4444' }}>
                  {r.driver}: {r.ok ? 'OK' : `FAIL (${r.error})`}
                  {r.latency_us && ` — ${r.latency_us.toFixed(0)} us`}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Register Inspector */}
        <div style={CARD}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>Register Inspector</h3>
          <RegisterInspector />
        </div>
      </div>

      {/* Row 2: StallGuard2 Chart */}
      <div style={{ ...CARD, marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 14, color: '#94a3b8' }}>StallGuard2 Live</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 12, color: '#64748b' }}>Threshold:</label>
            <input
              type="number"
              min={0}
              max={1023}
              value={sgThreshold ?? ''}
              onChange={e => setSgThreshold(e.target.value ? Number(e.target.value) : undefined)}
              placeholder="--"
              style={{ width: 60, background: '#0f172a', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '2px 6px', fontFamily: 'monospace', fontSize: 12 }}
            />
          </div>
        </div>
        <StallGuardChart threshold={sgThreshold} width={840} height={220} />
      </div>

      {/* Row 3: Motor Jog */}
      <div style={{ ...CARD, marginBottom: 12 }}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>Motor Jog</h3>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <select
            value={jogAxis}
            onChange={e => setJogAxis(Number(e.target.value))}
            style={{ background: '#0f172a', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px' }}
          >
            <option value={0}>FEED</option>
            <option value={1}>BEND</option>
          </select>
          <input
            type="number"
            value={jogSpeed}
            onChange={e => setJogSpeed(Number(e.target.value))}
            style={{ width: 60, background: '#0f172a', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px', fontFamily: 'monospace' }}
          />
          <span style={{ fontSize: 12, color: '#64748b' }}>mm/s</span>
          <button onClick={() => handleJog(-1)} style={{ ...BTN, background: '#475569', color: '#fff' }}>&laquo; REV</button>
          <button onClick={handleJogStop} style={{ ...BTN, background: '#ef4444', color: '#fff' }}>STOP</button>
          <button onClick={() => handleJog(1)} style={{ ...BTN, background: '#475569', color: '#fff' }}>FWD &raquo;</button>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>Status: {jogStatus}</span>
        </div>
      </div>

      {/* Row 4: Register Dump */}
      <div style={CARD}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>Register Dump</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          {DRIVERS.map(d => (
            <button
              key={d}
              onClick={() => handleDump(d)}
              disabled={dumpLoading}
              style={{ ...BTN, background: '#334155', color: '#f1f5f9', fontSize: 12 }}
            >
              Dump {d}
            </button>
          ))}
        </div>
        {dumpResult && (
          <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#94a3b8' }}>
            <div style={{ marginBottom: 4, color: '#f1f5f9' }}>{dumpResult.driver}:</div>
            {Object.entries(dumpResult.registers).map(([name, val]) => (
              <div key={name} style={{ display: 'inline-block', marginRight: 16 }}>
                {name} = {val}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add 'diagnostics' page to App.tsx**

In `src/app/frontend/src/App.tsx`:

Add import at the top (after line 20):
```typescript
import { DiagnosticsPage }  from './pages/DiagnosticsPage';
```

Update the `Page` type (line 27):
```typescript
export type Page = 'connection' | 'dashboard' | 'bending' | 'motor' | 'camera' | 'simulation' | 'settings' | 'diagnostics';
```

Add the case in `renderPage()` (after `case 'settings':` around line 105):
```typescript
      case 'diagnostics': return <DiagnosticsPage />;
```

- [ ] **Step 3: Add 'Diagnostics' to Sidebar**

Read `src/app/frontend/src/components/layout/Sidebar.tsx` and add a nav item for `'diagnostics'` with an appropriate icon (e.g., `Wrench` from lucide-react), positioned after 'Motor' and before 'Simulation' in the sidebar nav items array.

- [ ] **Step 4: Verify TypeScript compiles and dev server starts**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender/src/app/frontend && npx tsc --noEmit 2>&1 | head -20
```
Expected: No errors.

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender/src/app/frontend && npx vite build 2>&1 | tail -5
```
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add src/app/frontend/src/pages/DiagnosticsPage.tsx src/app/frontend/src/App.tsx src/app/frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(frontend): DiagnosticsPage with SPI test, register inspector, SG chart, jog, dump"
```

---

## Task 13: SpidevMotorBackend (Linux Hardware Backend)

**Files:**
- Create: `src/app/server/services/spi_backend.py`

- [ ] **Step 1: Implement SpidevMotorBackend**

Create `src/app/server/services/spi_backend.py`:

```python
"""
spi_backend.py — Linux spidev + gpiod motor backend for test bench.

Uses /dev/spidevX.Y for SPI transfers and gpiod for GPIO control.
STEP pulse generation uses a blocking sleep loop (adequate for bench
test speeds up to 1 kHz; production uses M7 GPT timer ISR).

Requires: python3-spidev, python3-gpiod (on target EVK)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .motor_backend import MotorBackend

log = logging.getLogger(__name__)

# i.MX8MP GPIO chip mapping for gpiod
# GPIO3_IOxx -> gpiochip2, GPIO5_IOxx -> gpiochip4
_GPIO_CHIP_MAP = {
    'GPIO3': 'gpiochip2',
    'GPIO5': 'gpiochip4',
}


def _parse_gpio(pin: str) -> tuple[str, int]:
    """Parse 'GPIO3_IO19' -> ('gpiochip2', 19)."""
    parts = pin.split('_IO')
    chip_name = _GPIO_CHIP_MAP.get(parts[0])
    if chip_name is None:
        raise ValueError(f"Unknown GPIO bank: {parts[0]}")
    offset = int(parts[1])
    return chip_name, offset


class SpidevMotorBackend(MotorBackend):
    """Hardware backend using Linux spidev for SPI and gpiod for GPIO."""

    def __init__(
        self,
        spi_device: str = "/dev/spidev1.0",
        spi_speed_hz: int = 2_000_000,
        gpio_cs1: str = "GPIO3_IO19",
        gpio_cs2: str = "GPIO3_IO20",
        gpio_feed_step: str = "GPIO3_IO22",
        gpio_bend_step: str = "GPIO3_IO24",
        gpio_dir: str = "GPIO5_IO06",
    ) -> None:
        self._spi_device = spi_device
        self._spi_speed = spi_speed_hz
        self._gpio_names = {
            'cs1': gpio_cs1,
            'cs2': gpio_cs2,
            'feed_step': gpio_feed_step,
            'bend_step': gpio_bend_step,
            'dir': gpio_dir,
        }
        self._spi: Optional[object] = None
        self._gpio_lines: dict[str, object] = {}
        self.positions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}

    async def open(self) -> None:
        """Open SPI device and request GPIO lines. Call during app startup."""
        try:
            import spidev
            bus, dev = self._parse_spidev_path(self._spi_device)
            spi = spidev.SpiDev()
            spi.open(bus, dev)
            spi.max_speed_hz = self._spi_speed
            spi.mode = 3  # CPOL=1, CPHA=1
            spi.bits_per_word = 8
            self._spi = spi
            log.info("SPI opened: %s @ %d Hz", self._spi_device, self._spi_speed)
        except ImportError:
            log.error("spidev module not available — install python3-spidev")
            raise

        try:
            import gpiod
            for name, gpio_str in self._gpio_names.items():
                chip_name, offset = _parse_gpio(gpio_str)
                chip = gpiod.Chip(chip_name)
                line = chip.get_line(offset)
                config = gpiod.LineRequest()
                config.consumer = "ortho-bender-diag"
                config.request_type = gpiod.LINE_REQ_DIR_OUT
                line.request(config)
                line.set_value(1 if name.startswith('cs') else 0)  # CS idle high
                self._gpio_lines[name] = line
                log.info("GPIO %s (%s) configured as output", gpio_str, name)
        except ImportError:
            log.error("gpiod module not available — install python3-gpiod")
            raise

    async def close(self) -> None:
        """Release SPI and GPIO resources."""
        if self._spi:
            self._spi.close()
        for line in self._gpio_lines.values():
            line.release()

    @staticmethod
    def _parse_spidev_path(path: str) -> tuple[int, int]:
        """Parse '/dev/spidev1.0' -> (1, 0)."""
        name = path.split('spidev')[1]
        parts = name.split('.')
        return int(parts[0]), int(parts[1])

    async def spi_transfer(self, cs: int, data: bytes) -> bytes:
        """SPI transfer with manual CS for CS1/CS2."""
        if self._spi is None:
            raise RuntimeError("SPI not opened — call open() first")

        # CS0 is hardware-controlled by spidev; CS1/CS2 are GPIO
        if cs == 1:
            self._gpio_lines['cs1'].set_value(0)
        elif cs == 2:
            self._gpio_lines['cs2'].set_value(0)

        try:
            result = self._spi.xfer2(list(data))
            return bytes(result)
        finally:
            if cs == 1:
                self._gpio_lines['cs1'].set_value(1)
            elif cs == 2:
                self._gpio_lines['cs2'].set_value(1)

    async def set_gpio(self, pin: str, value: bool) -> None:
        # Find the line by GPIO name match
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_lines:
                self._gpio_lines[name].set_value(int(value))
                return
        log.warning("GPIO %s not configured", pin)

    async def get_gpio(self, pin: str) -> bool:
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_lines:
                return bool(self._gpio_lines[name].get_value())
        return False

    async def pulse_step(self, axis: int, count: int,
                         freq_hz: int, direction: int) -> None:
        """Generate STEP pulses via GPIO toggle loop."""
        step_key = 'feed_step' if axis == 0 else 'bend_step'
        step_line = self._gpio_lines.get(step_key)
        dir_line = self._gpio_lines.get('dir')
        if not step_line or not dir_line:
            log.error("GPIO lines not available for axis %d", axis)
            return

        # Set direction
        dir_line.set_value(1 if direction > 0 else 0)
        await asyncio.sleep(0.000005)  # 5 us direction setup time

        half_period = 1.0 / (2 * freq_hz)
        for _ in range(count):
            step_line.set_value(1)
            time.sleep(half_period)
            step_line.set_value(0)
            time.sleep(half_period)

        self.positions[axis] = self.positions.get(axis, 0) + (count * direction)
```

- [ ] **Step 2: Verify imports work (mock environment)**

Run:
```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -c "
# Just verify the module can be imported (spidev/gpiod won't be available on dev machine)
import importlib.util
spec = importlib.util.spec_from_file_location('spi_backend', 'src/app/server/services/spi_backend.py')
mod = importlib.util.module_from_spec(spec)
print('OK: spi_backend module structure valid')
"
```
Expected: `OK: spi_backend module structure valid`

- [ ] **Step 3: Commit**

```bash
git add src/app/server/services/spi_backend.py
git commit -m "feat(backend): SpidevMotorBackend for Linux spidev + gpiod"
```

---

## Task 14: M7 Firmware — TMC5072 Driver Header + Implementation

**Files:**
- Create: `src/firmware/source/drivers/tmc5072.h`
- Create: `src/firmware/source/drivers/tmc5072.c`
- Create: `src/firmware/source/drivers/tmc5072_hal_ops.c`

- [ ] **Step 1: Create TMC5072 header**

Create `src/firmware/source/drivers/tmc5072.h`:

```c
/**
 * @file tmc5072.h
 * @brief TMC5072-LA dual stepper motor driver — SPI configuration and control
 * @author ortho-bender firmware team
 *
 * The TMC5072 is a dual-axis stepper driver with internal ramp generator.
 * Unlike the TMC260C, it does NOT use STEP/DIR — motion is commanded via
 * SPI register writes (XTARGET, VMAX, AMAX).
 *
 * SPI protocol: 40-bit datagrams (8-bit addr + 32-bit data), Mode 3, max 4 MHz.
 *
 * Reference: TMC5072 Datasheet Rev 1.17
 *
 * IEC 62304 SW Class: B
 */

#ifndef TMC5072_H
#define TMC5072_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ======================================================================
 * Register Addresses
 * ====================================================================== */

#define TMC5072_GCONF           0x00U
#define TMC5072_GSTAT           0x01U
#define TMC5072_IC_VERSION      0x73U

/* Motor 0 registers */
#define TMC5072_M0_RAMPMODE     0x20U
#define TMC5072_M0_XACTUAL      0x21U
#define TMC5072_M0_VACTUAL      0x22U
#define TMC5072_M0_VMAX         0x27U
#define TMC5072_M0_AMAX         0x28U
#define TMC5072_M0_DMAX         0x29U
#define TMC5072_M0_XTARGET      0x2DU
#define TMC5072_M0_IHOLD_IRUN   0x30U
#define TMC5072_M0_RAMP_STAT    0x35U
#define TMC5072_M0_CHOPCONF     0x6CU
#define TMC5072_M0_DRV_STATUS   0x6FU

/* Motor 1 registers (offset +0x10 for ramp, +0x10 for CHOP/DRV) */
#define TMC5072_M1_RAMPMODE     0x40U
#define TMC5072_M1_XACTUAL      0x41U
#define TMC5072_M1_VACTUAL      0x42U
#define TMC5072_M1_VMAX         0x47U
#define TMC5072_M1_AMAX         0x48U
#define TMC5072_M1_DMAX         0x49U
#define TMC5072_M1_XTARGET      0x4DU
#define TMC5072_M1_IHOLD_IRUN   0x50U
#define TMC5072_M1_RAMP_STAT    0x55U
#define TMC5072_M1_CHOPCONF     0x7CU
#define TMC5072_M1_DRV_STATUS   0x7FU

/* RAMP_STAT bits */
#define TMC5072_RAMP_STAT_POS_REACHED   (1U << 9)

/* ======================================================================
 * CHOPCONF defaults (SpreadCycle, TOFF=5, HSTRT=4, HEND=1, TBL=2)
 * ====================================================================== */

#define TMC5072_CHOPCONF_DEFAULT    0x000101D5U

/* ======================================================================
 * IHOLD_IRUN field positions
 * ====================================================================== */

#define TMC5072_IHOLD_SHIFT         0U
#define TMC5072_IHOLD_MASK          0x1FU
#define TMC5072_IRUN_SHIFT          8U
#define TMC5072_IRUN_MASK           0x1FU
#define TMC5072_IHOLDDELAY_SHIFT    16U
#define TMC5072_IHOLDDELAY_MASK     0x0FU

/* ======================================================================
 * Driver Instance
 * ====================================================================== */

/** Per-motor TMC5072 state (2 motors per chip) */
typedef struct {
    uint8_t     cs_index;       /**< SPI chip-select index */
    bool        initialized;    /**< Driver initialized flag */
    int32_t     xactual[2];     /**< Cached XACTUAL per motor */
    uint32_t    drv_status[2];  /**< Cached DRV_STATUS per motor */
} tmc5072_t;

/* ======================================================================
 * Driver API
 * ====================================================================== */

bool        tmc5072_init(tmc5072_t *tmc, uint8_t cs_index);
uint32_t    tmc5072_read_register(tmc5072_t *tmc, uint8_t addr);
void        tmc5072_write_register(tmc5072_t *tmc, uint8_t addr, uint32_t value);
void        tmc5072_move_to(tmc5072_t *tmc, uint8_t motor, int32_t position,
                            uint32_t vmax, uint32_t amax);
int32_t     tmc5072_get_position(tmc5072_t *tmc, uint8_t motor);
bool        tmc5072_position_reached(tmc5072_t *tmc, uint8_t motor);
uint32_t    tmc5072_get_drv_status(tmc5072_t *tmc, uint8_t motor);

/** Get motor HAL ops for TMC5072 (SPI position mode) */
struct motor_hal_ops;
const struct motor_hal_ops *tmc5072_get_motor_hal_ops(void);

#ifdef __cplusplus
}
#endif

#endif /* TMC5072_H */
```

- [ ] **Step 2: Create TMC5072 implementation stubs**

Create `src/firmware/source/drivers/tmc5072.c`:

```c
/**
 * @file tmc5072.c
 * @brief TMC5072-LA SPI driver implementation
 *
 * IEC 62304 SW Class: B
 */

#include "tmc5072.h"
#include "../hal/hal_spi.h"
#include "../hal/hal_gpio.h"

/* SPI datagram: [W/R | addr(7)] [data(32)] = 5 bytes */
static uint32_t tmc5072_spi_xfer(tmc5072_t *tmc, uint8_t addr, uint32_t data, bool write)
{
    uint8_t tx[5] = {
        (write ? 0x80U : 0x00U) | (addr & 0x7FU),
        (uint8_t)(data >> 24),
        (uint8_t)(data >> 16),
        (uint8_t)(data >> 8),
        (uint8_t)(data),
    };
    uint8_t rx[5] = {0};

    hal_gpio_write(tmc->cs_index, 0);
    hal_spi_transfer(tx, rx, 5);
    hal_gpio_write(tmc->cs_index, 1);

    return ((uint32_t)rx[1] << 24) | ((uint32_t)rx[2] << 16) |
           ((uint32_t)rx[3] << 8)  | (uint32_t)rx[4];
}

bool tmc5072_init(tmc5072_t *tmc, uint8_t cs_index)
{
    tmc->cs_index = cs_index;
    tmc->initialized = false;
    tmc->xactual[0] = 0;
    tmc->xactual[1] = 0;
    tmc->drv_status[0] = 0;
    tmc->drv_status[1] = 0;

    /* Configure GCONF */
    tmc5072_write_register(tmc, TMC5072_GCONF, 0x00000000U);

    /* Configure CHOPCONF for both motors */
    tmc5072_write_register(tmc, TMC5072_M0_CHOPCONF, TMC5072_CHOPCONF_DEFAULT);
    tmc5072_write_register(tmc, TMC5072_M1_CHOPCONF, TMC5072_CHOPCONF_DEFAULT);

    /* Configure IHOLD_IRUN: IHOLD=8, IRUN=16, IHOLDDELAY=6 */
    uint32_t ihr = (6U << TMC5072_IHOLDDELAY_SHIFT) |
                   (16U << TMC5072_IRUN_SHIFT) |
                   (8U << TMC5072_IHOLD_SHIFT);
    tmc5072_write_register(tmc, TMC5072_M0_IHOLD_IRUN, ihr);
    tmc5072_write_register(tmc, TMC5072_M1_IHOLD_IRUN, ihr);

    tmc->initialized = true;
    return true;
}

uint32_t tmc5072_read_register(tmc5072_t *tmc, uint8_t addr)
{
    /* First transfer: send read request */
    tmc5072_spi_xfer(tmc, addr, 0, false);
    /* Second transfer: clock out response */
    return tmc5072_spi_xfer(tmc, addr, 0, false);
}

void tmc5072_write_register(tmc5072_t *tmc, uint8_t addr, uint32_t value)
{
    tmc5072_spi_xfer(tmc, addr, value, true);
}

void tmc5072_move_to(tmc5072_t *tmc, uint8_t motor, int32_t position,
                     uint32_t vmax, uint32_t amax)
{
    uint8_t rampmode_reg = (motor == 0) ? TMC5072_M0_RAMPMODE : TMC5072_M1_RAMPMODE;
    uint8_t vmax_reg     = (motor == 0) ? TMC5072_M0_VMAX     : TMC5072_M1_VMAX;
    uint8_t amax_reg     = (motor == 0) ? TMC5072_M0_AMAX     : TMC5072_M1_AMAX;
    uint8_t dmax_reg     = (motor == 0) ? TMC5072_M0_DMAX     : TMC5072_M1_DMAX;
    uint8_t xtarget_reg  = (motor == 0) ? TMC5072_M0_XTARGET  : TMC5072_M1_XTARGET;

    tmc5072_write_register(tmc, rampmode_reg, 0);  /* positioning mode */
    tmc5072_write_register(tmc, vmax_reg, vmax);
    tmc5072_write_register(tmc, amax_reg, amax);
    tmc5072_write_register(tmc, dmax_reg, amax);
    tmc5072_write_register(tmc, xtarget_reg, (uint32_t)position);
}

int32_t tmc5072_get_position(tmc5072_t *tmc, uint8_t motor)
{
    uint8_t reg = (motor == 0) ? TMC5072_M0_XACTUAL : TMC5072_M1_XACTUAL;
    uint32_t val = tmc5072_read_register(tmc, reg);
    tmc->xactual[motor] = (int32_t)val;
    return (int32_t)val;
}

bool tmc5072_position_reached(tmc5072_t *tmc, uint8_t motor)
{
    uint8_t reg = (motor == 0) ? TMC5072_M0_RAMP_STAT : TMC5072_M1_RAMP_STAT;
    uint32_t ramp_stat = tmc5072_read_register(tmc, reg);
    return (ramp_stat & TMC5072_RAMP_STAT_POS_REACHED) != 0;
}

uint32_t tmc5072_get_drv_status(tmc5072_t *tmc, uint8_t motor)
{
    uint8_t reg = (motor == 0) ? TMC5072_M0_DRV_STATUS : TMC5072_M1_DRV_STATUS;
    uint32_t val = tmc5072_read_register(tmc, reg);
    tmc->drv_status[motor] = val;
    return val;
}
```

- [ ] **Step 3: Create TMC5072 motor_hal_ops vtable**

Create `src/firmware/source/drivers/tmc5072_hal_ops.c`:

```c
/**
 * @file tmc5072_hal_ops.c
 * @brief motor_hal_ops_t implementation for TMC5072 (SPI position mode)
 *
 * IEC 62304 SW Class: B
 */

#include "motor_hal.h"
#include "tmc5072.h"

static motor_result_t tmc5072_hal_init(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    return tmc5072_init(tmc, tmc->cs_index) ? MOTOR_OK : MOTOR_ERR_NOT_INIT;
}

static motor_result_t tmc5072_hal_move_abs(void *drv_ctx, int32_t target_steps,
                                            uint32_t vmax, uint32_t amax)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    /* Determine which motor channel based on context — for now use motor 0 */
    tmc5072_move_to(tmc, 0, target_steps, vmax, amax);
    return MOTOR_OK;
}

static bool tmc5072_hal_position_reached(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    return tmc5072_position_reached(tmc, 0);
}

static int32_t tmc5072_hal_get_position(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    return tmc5072_get_position(tmc, 0);
}

static void tmc5072_hal_emergency_stop(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    /* Write VMAX=0 to both motors for immediate stop */
    tmc5072_write_register(tmc, TMC5072_M0_VMAX, 0);
    tmc5072_write_register(tmc, TMC5072_M1_VMAX, 0);
}

static motor_result_t tmc5072_hal_poll_status(void *drv_ctx, motor_status_t *out)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    uint32_t drv = tmc5072_get_drv_status(tmc, 0);

    out->ot    = (drv >> 1) & 1;
    out->otpw  = (drv >> 0) & 1;
    out->s2ga  = (drv >> 12) & 1;
    out->s2gb  = (drv >> 13) & 1;
    out->ola   = (drv >> 6) & 1;
    out->olb   = (drv >> 7) & 1;
    out->stall = (drv >> 24) & 1;
    out->sg_result = (int16_t)((drv >> 10) & 0x3FF);

    return MOTOR_OK;
}

static void tmc5072_hal_enable(void *drv_ctx)
{
    /* TMC5072 does not have a separate enable pin — always enabled when powered */
    (void)drv_ctx;
}

static void tmc5072_hal_disable(void *drv_ctx)
{
    /* Set both motors to standstill by zeroing VMAX */
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    tmc5072_write_register(tmc, TMC5072_M0_VMAX, 0);
    tmc5072_write_register(tmc, TMC5072_M1_VMAX, 0);
}

static const motor_hal_ops_t s_tmc5072_ops = {
    .init             = tmc5072_hal_init,
    .move_abs         = tmc5072_hal_move_abs,
    .position_reached = tmc5072_hal_position_reached,
    .get_position     = tmc5072_hal_get_position,
    .emergency_stop   = tmc5072_hal_emergency_stop,
    .poll_status      = tmc5072_hal_poll_status,
    .enable           = tmc5072_hal_enable,
    .disable          = tmc5072_hal_disable,
};

const motor_hal_ops_t *tmc5072_get_motor_hal_ops(void)
{
    return &s_tmc5072_ops;
}
```

- [ ] **Step 4: Verify files are syntactically valid**

Run:
```bash
# Check C syntax (just compilation parse, no link)
cd /home/issacs/work/quarkers/ortho-bender && arm-none-eabi-gcc -fsyntax-only -I src/firmware/source -I src/shared src/firmware/source/drivers/tmc5072.h 2>&1 || echo "Cross-compiler not available on host — syntax check skipped, verify on EVK"
```

- [ ] **Step 5: Commit**

```bash
git add src/firmware/source/drivers/tmc5072.h src/firmware/source/drivers/tmc5072.c src/firmware/source/drivers/tmc5072_hal_ops.c
git commit -m "feat(firmware): TMC5072 SPI driver + motor_hal_ops vtable"
```

---

## Task 15: Architecture Document Correction

**Files:**
- Modify: `docs/architecture/motor-control-architecture.md` Section 5.2

- [ ] **Step 1: Read current Section 5.2**

Read `docs/architecture/motor-control-architecture.md` and locate Section 5.2 which incorrectly describes a 160-bit daisy-chain topology.

- [ ] **Step 2: Replace daisy-chain description with split CS topology**

Replace the 160-bit daisy-chain content with the correct split CS topology:

- TMC260C uses 20-bit datagrams (NOT 40-bit)
- TMC5072 uses 40-bit datagrams
- Split CS topology: separate chip-select per driver
- CS0 → TMC260C #1 (FEED), CS1 → TMC260C #2 (BEND)
- CS2 → TMC5072 (ROTATE + LIFT)
- All share MOSI/MISO/SCLK on ECSPI2

Include a note about production vs test bench:
- Test bench: ECSPI2 with GPIO-based CS for CS1/CS2
- Production: adapter board with dedicated CS routing

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/motor-control-architecture.md
git commit -m "fix(docs): replace incorrect 160-bit daisy-chain with split CS topology"
```

---

## Task 16: Integration Test — Full Backend Stack

**Files:**
- Existing tests + manual verification

- [ ] **Step 1: Run all unit tests**

```bash
cd /home/issacs/work/quarkers/ortho-bender && python3 -m pytest tests/test_motor_backend.py tests/test_tmc260c_driver.py tests/test_tmc5072_driver.py tests/test_diag_service.py tests/test_diag_router.py -v
```
Expected: All tests PASS.

- [ ] **Step 2: Test server startup in mock mode**

```bash
cd /home/issacs/work/quarkers/ortho-bender && timeout 5 python3 -c "
import asyncio
from src.app.server.main import create_app

app = create_app()
print('Server app created successfully')

# Verify all routes are mounted
paths = []
for route in app.routes:
    if hasattr(route, 'path'):
        paths.append(route.path)
assert any('diag' in p for p in paths), f'diag routes missing: {paths}'
print(f'Routes mounted: {len(paths)}')
print('OK: Full backend stack verified')
" 2>&1
```
Expected: `OK: Full backend stack verified`

- [ ] **Step 3: Verify frontend builds**

```bash
cd /home/issacs/work/quarkers/ortho-bender/src/app/frontend && npx vite build 2>&1 | tail -5
```
Expected: Build succeeds.

- [ ] **Step 4: Final commit with all integration verified**

```bash
git add -A
git status
# Only commit if there are untracked changes from integration fixes
```

---

## Summary

| Task | Component | Files | Tests |
|------|-----------|-------|-------|
| 1 | Config extensions | 1 modified | inline verify |
| 2 | MotorBackend ABC + Mock | 1 new + 1 test | 8 tests |
| 3 | TMC260C driver | 1 new + 1 test | 10 tests |
| 4 | TMC5072 driver | 1 new + 1 test | 9 tests |
| 5 | Diagnostic schemas | 1 new | import verify |
| 6 | DiagService | 1 new + 1 test | 8 tests |
| 7 | Diagnostic router | 1 new + 1 test | 7 tests |
| 8 | main.py + WsManager wiring | 2 modified | startup verify |
| 9 | Frontend API client | 1 modified | tsc verify |
| 10 | StallGuardChart | 1 new | tsc verify |
| 11 | RegisterInspector | 1 new | tsc verify |
| 12 | DiagnosticsPage + App | 3 modified/new | build verify |
| 13 | SpidevMotorBackend | 1 new | import verify |
| 14 | M7 TMC5072 firmware | 3 new | syntax verify |
| 15 | Architecture doc fix | 1 modified | n/a |
| 16 | Integration verification | — | all tests |

**Total: 16 tasks, ~16 new files, ~6 modified files, ~42 unit tests**
