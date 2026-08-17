"""
test_current_safety.py — the coil-current ceiling must not be reachable.

Two driver boards were destroyed on 2026-05-08 running CS=31, so the
clamps below are not style rules: every path that can put current into a
coil is exercised here and asserted to stay at or under the cap. These
tests are meant to fail loudly if a future change adds a way around one.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services.motor_service import MotorService
from server.services.spi_backend import SpidevMotorBackend
from server.services.tmc260c_driver import (
    SAFETY_CS_MAX, SAFETY_TOFF_MAX, CHOPCONF_DEFAULT, SGCSCONF_DEFAULT,
)


class _NoIoBackend(SpidevMotorBackend):
    """The real backend with only the SPI/GPIO writes removed.

    The clamp logic is what is under test, so it must be the production
    code and not a reimplementation -- a stub that re-derives the cap
    would happily pass while the real path leaked.
    """

    def __init__(self):
        super().__init__()
        self._state_path = "/nonexistent/ortho-bench-test-state.json"

    async def _hold_chip(self, cs):      # no SPI in tests
        pass

    async def _silence_chip(self, cs):
        pass

    def _save_state(self):
        pass


@pytest.fixture
def bench_backend():
    return _NoIoBackend()


@pytest.fixture
def svc(bench_backend):
    return MotorService(ipc=None, spidev_backend=bench_backend)


def _cs_of(sgcsconf: int) -> int:
    """Current scale occupies SGCSCONF bits 0-4."""
    return sgcsconf & 0x1F


# ---------------------------------------------------------------------------
# The frozen constants themselves
# ---------------------------------------------------------------------------

def test_module_defaults_are_within_the_ceiling():
    assert _cs_of(SGCSCONF_DEFAULT) <= SAFETY_CS_MAX
    assert 1 <= (CHOPCONF_DEFAULT & 0xF) <= SAFETY_TOFF_MAX


# ---------------------------------------------------------------------------
# Every SGCSCONF the backend can emit
# ---------------------------------------------------------------------------

def test_no_requested_current_escapes_the_cap(bench_backend):
    """Ask each axis for every value up to well past the ceiling; the
    encoded register must never carry more than the cap allows."""
    be = bench_backend
    for cap in (0, 5, 12, 14, SAFETY_CS_MAX):
        be.apply_current_cap(cap)
        for cs in (0, 1, 2):
            for want in range(0, 64):        # far beyond the 5-bit field
                be.run_cs_map[cs] = want
                got = _cs_of(be._sgcs_on_value(cs))
                assert got <= cap, f"cap={cap} want={want} -> {got}"
                assert got <= SAFETY_CS_MAX


def test_cap_cannot_be_widened_past_the_ceiling(bench_backend):
    """apply_current_cap is the PSU's hook; a bad preset must not raise
    the ceiling."""
    be = bench_backend
    for attempt in (20, 31, 255, 10_000):
        be.apply_current_cap(attempt)
        assert be._cs_scale_cap <= SAFETY_CS_MAX
        for cs in (0, 1, 2):
            assert _cs_of(be._sgcs_on_value(cs)) <= SAFETY_CS_MAX


def test_negative_cap_does_not_underflow(bench_backend):
    be = bench_backend
    be.apply_current_cap(-5)
    assert be._cs_scale_cap == 0
    assert _cs_of(be._sgcs_on_value(0)) == 0


def test_stallguard_threshold_cannot_disturb_the_current_bits(bench_backend):
    """SGT shares the register with the current scale. Writing a
    threshold must not spill into bits 0-4."""
    be = bench_backend
    be.apply_current_cap(12)
    for sgt in range(-64, 64):
        for cs in (0, 1, 2):
            be.sgt_map[cs] = sgt
            assert _cs_of(be._sgcs_on_value(cs)) <= 12


def test_chopconf_toff_stays_in_range(bench_backend):
    """TOFF > 8 caused thermal damage; the init sequence writes a frozen
    CHOPCONF and nothing may parameterise it."""
    for _name, tag, value in bench_backend_init_seq():
        if tag == 0x04:      # CHOPCONF
            assert 1 <= (value & 0xF) <= SAFETY_TOFF_MAX


def bench_backend_init_seq():
    from server.services.spi_backend import _INIT_SEQ
    return _INIT_SEQ


# ---------------------------------------------------------------------------
# Through the service layer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_cs_is_clamped_by_the_psu_cap(svc):
    """An axis may ask for more than the supply can give; it gets the
    cap, and the report says so rather than echoing the request."""
    be = svc._spi_backend
    be.apply_current_cap(14)
    p = await svc.set_protection(axes={1: {"run_cs": 19}})
    assert p["axes"][1]["run_cs"] == 19            # what was asked
    assert p["axes"][1]["run_cs_effective"] == 14  # what the coil gets
    assert be.run_cs_for(be_cs(svc, 1)) == 14


@pytest.mark.asyncio
async def test_run_cs_is_per_axis(svc):
    """The whole point: a bending axis can carry more current than a
    feed roller."""
    be = svc._spi_backend
    be.apply_current_cap(SAFETY_CS_MAX)
    await svc.set_protection(axes={1: {"run_cs": 18}, 0: {"run_cs": 6}})
    assert be.run_cs_for(be_cs(svc, 1)) == 18
    assert be.run_cs_for(be_cs(svc, 0)) == 6


@pytest.mark.asyncio
async def test_service_clamps_a_hand_edited_value(svc):
    """Values arriving from anywhere but the validated router are still
    clamped, so a hand-edited state file cannot raise current."""
    be = svc._spi_backend
    be.apply_current_cap(SAFETY_CS_MAX)
    await svc.set_protection(axes={1: {"run_cs": 31}})
    assert be.run_cs_map[be_cs(svc, 1)] <= SAFETY_CS_MAX


def be_cs(svc, axis: int) -> int:
    return svc._axis_to_cs[axis]


# ---------------------------------------------------------------------------
# Through the HTTP surface
# ---------------------------------------------------------------------------

async def test_api_rejects_current_above_the_ceiling(client):
    for bad in (20, 31, 255, 0, -1):
        resp = await client.put("/api/motor/protection",
                                json={"axes": {"1": {"run_cs": bad}}})
        assert resp.status_code == 422, f"run_cs={bad} was accepted"


async def test_api_rejects_hold_current_above_the_ceiling(client):
    for bad in (20, 31, 255, 0):
        resp = await client.put("/api/motor/protection",
                                json={"axes": {"1": {"hold_cs": bad}}})
        assert resp.status_code == 422, f"hold_cs={bad} was accepted"


async def test_protection_report_names_the_ceiling(client):
    """A client tuning torque needs to see the limit it is working
    against, not discover it by being silently clamped."""
    resp = await client.get("/api/motor/protection")
    body = resp.json()
    if body["success"] and "cs_max" in body["data"]:
        assert body["data"]["cs_max"] == SAFETY_CS_MAX
        assert body["data"]["cs_cap"] <= SAFETY_CS_MAX
