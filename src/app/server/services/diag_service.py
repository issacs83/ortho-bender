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
    DriverProbeResult,
    SpiTestResult,
)
from .tmc260c_driver import (
    Tmc260cDriver,
    SAFETY_CS_MAX,
    SAFETY_TOFF_MAX,
    REG_CHOPCONF,
    REG_SGCSCONF,
)
from .tmc5072_driver import Tmc5072Driver


class UnsafeRegisterWrite(ValueError):
    """Raised when a /diag/register POST tries to set a known-dangerous value.

    HARD GATE — see safety_motor_register_limits.md. The 2026-05-08 incident
    burned two boards because CS=31 + TOFF=15 was applied via raw SPI. The
    diagnostic UI must not be a back-door around the safety limits enforced
    by Tmc260cDriver.set_current()/set_chopconf().
    """


def _validate_tmc260c_write(addr: int, value: int, psu_cs_cap: int = SAFETY_CS_MAX) -> None:
    """Reject writes that would put the TMC260C-PA outside the safe envelope.

    Two layers of protection:
      1. SAFETY_CS_MAX / SAFETY_TOFF_MAX — absolute hardware limits, never
         exceeded under any condition (boards burned 2026-05-08).
      2. psu_cs_cap — per-PSU cap from PsuService. A 2 A brick can't
         sustain three coils at CS=19, so the active preset narrows the
         allowed CS down even though the chip itself would tolerate it.

    Affected registers:
      - CHOPCONF (0x04): TOFF (bits[3:0]) must be <= SAFETY_TOFF_MAX (8).
      - SGCSCONF (0x06): CS  (bits[4:0]) must be <= effective_cs_cap.
    Other registers (DRVCTRL, SMARTEN, DRVCONF) are allowed through —
    they don't directly drive coil current/dissipation.
    """
    if addr == REG_CHOPCONF:
        toff = value & 0x0F
        if toff > SAFETY_TOFF_MAX:
            raise UnsafeRegisterWrite(
                f"CHOPCONF TOFF={toff} exceeds safety limit {SAFETY_TOFF_MAX}. "
                f"2026-05-08 incident burned boards with TOFF>8."
            )
    elif addr == REG_SGCSCONF:
        cs = value & 0x1F
        # Hardware cap first — CS>19 burns the driver regardless of PSU.
        if cs > SAFETY_CS_MAX:
            raise UnsafeRegisterWrite(
                f"SGCSCONF CS={cs} exceeds safety limit {SAFETY_CS_MAX}. "
                f"2026-05-08 incident burned boards with CS>19."
            )
        # PSU-level cap — driver tolerant but supply not. Do this only
        # after the absolute check so the error message is the most
        # serious applicable one.
        effective = min(SAFETY_CS_MAX, psu_cs_cap)
        if cs > effective:
            raise UnsafeRegisterWrite(
                f"SGCSCONF CS={cs} exceeds PSU-derived cap {effective}. "
                f"Lift the cap by selecting a higher-rated supply in Settings."
            )

if TYPE_CHECKING:
    from .motor_backend import MotorBackend

log = logging.getLogger(__name__)


class DiagService:
    """Diagnostic service for low-level TMC driver access.

    Optionally consults a PsuService instance so register writes are
    validated against the operator-selected supply rating in addition to
    the absolute SAFETY_CS_MAX. The dependency is injected after
    construction (set_psu_service) to avoid an import cycle with main.py.
    """
    _psu_service = None  # late-injected via set_psu_service()

    def __init__(self, backend: MotorBackend) -> None:
        self._backend = backend
        # 3-axis bench mapping: cs=0/1/2 → LIFT/BEND/FEED (verified 2026-05-08)
        self._tmc260c_0 = Tmc260cDriver(backend, cs=0)  # LIFT
        self._tmc260c_1 = Tmc260cDriver(backend, cs=1)  # BEND
        self._tmc260c_2 = Tmc260cDriver(backend, cs=2)  # FEED
        # TMC5072 retained for future production board (uses cs=3 if present)
        self._tmc5072 = Tmc5072Driver(backend, cs=3)

    def set_psu_service(self, psu_service) -> None:
        """Wire in the PsuService so register writes can consult it."""
        self._psu_service = psu_service

    def _get_driver(self, driver_id: str) -> Tmc260cDriver | Tmc5072Driver:
        drivers: dict[str, Tmc260cDriver | Tmc5072Driver] = {
            "tmc260c_0": self._tmc260c_0,
            "tmc260c_1": self._tmc260c_1,
            "tmc260c_2": self._tmc260c_2,
            "tmc5072": self._tmc5072,
        }
        if driver_id not in drivers:
            raise ValueError(
                f"Unknown driver: {driver_id}. Valid: {list(drivers.keys())}"
            )
        return drivers[driver_id]

    async def probe_drivers(self) -> list[DriverProbeResult]:
        """Probe all motor driver CS lines and identify connected chips.

        Reads identification registers via SPI to determine which drivers
        are physically connected and what chip type they are.
        """
        results: list[DriverProbeResult] = []
        for did, drv in (
            (DriverId.TMC260C_0, self._tmc260c_0),
            (DriverId.TMC260C_1, self._tmc260c_1),
            (DriverId.TMC260C_2, self._tmc260c_2),
            (DriverId.TMC5072, self._tmc5072),
        ):
            connected, chip = await drv.probe()
            results.append(DriverProbeResult(
                driver=did, connected=connected, chip=chip,
            ))
            log.info("Driver probe %s: %s (%s)", did, "OK" if connected else "NOT FOUND", chip or "—")
        return results

    async def spi_test(self) -> list[SpiTestResult]:
        """Test SPI connectivity with all drivers."""
        results: list[SpiTestResult] = []
        for did in (DriverId.TMC260C_0, DriverId.TMC260C_1, DriverId.TMC260C_2, DriverId.TMC5072):
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

    async def write_register(
        self, driver_id: str, addr: int, value: int
    ) -> DiagRegisterResponse:
        """Write a value to a single register.

        HARD GATE: TMC260C CHOPCONF/SGCSCONF writes are validated against
        SAFETY_CS_MAX / SAFETY_TOFF_MAX before reaching SPI. Diagnostic UI
        must never become a path to apply unsafe coil current.
        """
        drv = self._get_driver(driver_id)
        if isinstance(drv, Tmc260cDriver):
            psu_cap = SAFETY_CS_MAX
            if self._psu_service is not None:
                psu_cap = self._psu_service.cs_cap
            _validate_tmc260c_write(addr, value, psu_cap)
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

    async def get_live_status(self) -> dict:
        """Return live diagnostic status for all drivers (for WS broadcast).

        Includes TMC260C x2 (StallGuard2 + fault flags) and
        TMC5072 motor 0/1 (DRV_STATUS register).
        """
        results = {}

        # TMC260C drivers (3-axis bench: LIFT/BEND/FEED) — full status with SG2, fault bits
        for did, drv in (
            ("tmc260c_0", self._tmc260c_0),  # LIFT
            ("tmc260c_1", self._tmc260c_1),  # BEND
            ("tmc260c_2", self._tmc260c_2),  # FEED
        ):
            try:
                status = await drv.read_status()
                results[did] = {
                    "sg_result": status.sg_result,
                    "stst": status.stst,
                    "ot": status.ot,
                    "otpw": status.otpw,
                    "s2ga": status.s2ga,
                    "s2gb": status.s2gb,
                    "ola": status.ola,
                    "olb": status.olb,
                }
            except Exception:
                results[did] = None

        # TMC5072 — 2 motor channels, DRV_STATUS per channel
        for motor in (0, 1):
            did = f"tmc5072_m{motor}"
            try:
                drv_status = await self._tmc5072.get_drv_status(motor)
                # TMC5072 DRV_STATUS bits: SG_RESULT[9:0], OT, OTPW, S2GA, S2GB, OLA, OLB, STST
                results[did] = {
                    "sg_result": drv_status & 0x3FF,
                    "stst": bool(drv_status & (1 << 31)),
                    "ot": bool(drv_status & (1 << 25)),
                    "otpw": bool(drv_status & (1 << 26)),
                    "s2ga": bool(drv_status & (1 << 27)),
                    "s2gb": bool(drv_status & (1 << 28)),
                    "ola": bool(drv_status & (1 << 29)),
                    "olb": bool(drv_status & (1 << 30)),
                }
            except Exception:
                results[did] = None

        return {"drivers": results}

    async def get_backend_info(self) -> DiagBackendResponse:
        """Return current backend mode and configuration."""
        backend_name = type(self._backend).__name__
        if "Mock" in backend_name:
            mode = "mock"
        elif "Spidev" in backend_name:
            mode = "spidev"
        else:
            mode = "m7"

        spi_device = getattr(self._backend, "_spi_device", None)
        spi_speed = getattr(self._backend, "_spi_speed", None)

        return DiagBackendResponse(
            backend=mode,
            spi_device=spi_device,
            spi_speed_hz=spi_speed,
            drivers=[DriverId.TMC260C_0, DriverId.TMC260C_1, DriverId.TMC260C_2, DriverId.TMC5072],
        )
