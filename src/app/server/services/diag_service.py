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
        drivers: dict[str, Tmc260cDriver | Tmc5072Driver] = {
            "tmc260c_0": self._tmc260c_0,
            "tmc260c_1": self._tmc260c_1,
            "tmc5072": self._tmc5072,
        }
        if driver_id not in drivers:
            raise ValueError(
                f"Unknown driver: {driver_id}. Valid: {list(drivers.keys())}"
            )
        return drivers[driver_id]

    async def spi_test(self) -> list[SpiTestResult]:
        """Test SPI connectivity with all drivers."""
        results: list[SpiTestResult] = []
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

    async def write_register(
        self, driver_id: str, addr: int, value: int
    ) -> DiagRegisterResponse:
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

    async def get_live_status(self) -> dict:
        """Return live diagnostic status for all TMC260C drivers (for WS broadcast)."""
        results = {}
        for did, drv in (("tmc260c_0", self._tmc260c_0), ("tmc260c_1", self._tmc260c_1)):
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
        return DiagBackendResponse(
            backend=mode,
            drivers=[DriverId.TMC260C_0, DriverId.TMC260C_1, DriverId.TMC5072],
        )
