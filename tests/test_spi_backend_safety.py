"""Unit tests for SpidevMotorBackend safety/current-cap logic.

These exercise the pure (no-hardware) parts of the bench backend: the
constructor performs no I/O, so the PSU current-cap plumbing and datagram
encoding are testable on any host without spidev/gpiod.
"""

import pytest

from src.app.server.services.spi_backend import SpidevMotorBackend, _INIT_SEQ
from src.app.server.services.tmc260c_driver import (
    SAFETY_CS_MAX,
    SGCSCONF_DEFAULT,
    DRVCTRL_DEFAULT,
)


@pytest.fixture
def backend():
    return SpidevMotorBackend()


def test_default_cap_is_hardware_limit(backend):
    assert backend._cs_scale_cap == SAFETY_CS_MAX
    assert backend._sgcs_on_value() == SGCSCONF_DEFAULT


def test_apply_current_cap_narrows_sgcsconf(backend):
    """A 12 V/2.9 A PSU (cs_cap=14) must narrow the init-time CS to 14."""
    backend.apply_current_cap(14)
    value = backend._sgcs_on_value()
    assert value & 0x1F == 14
    # Non-CS bits (SGT, SFILT) must be untouched.
    assert value & ~0x1F == SGCSCONF_DEFAULT & ~0x1F


def test_apply_current_cap_clamps_to_safety_max(backend):
    """A cap above SAFETY_CS_MAX must clamp — never widen past hardware."""
    backend.apply_current_cap(31)
    assert backend._cs_scale_cap == SAFETY_CS_MAX
    assert backend._sgcs_on_value() & 0x1F == SGCSCONF_DEFAULT & 0x1F


def test_apply_current_cap_rejects_negative(backend):
    backend.apply_current_cap(-5)
    assert backend._cs_scale_cap == 0
    assert backend._sgcs_on_value() & 0x1F == 0


def test_init_seq_uses_drvctrl_default():
    """_INIT_SEQ must program DRVCTRL_DEFAULT (1/16 + DEDGE), not a literal."""
    drvctrl = [v for name, tag, v in _INIT_SEQ if tag == 0x00]
    assert drvctrl == [DRVCTRL_DEFAULT]


def test_init_seq_defaults_within_safety():
    """CHOPCONF TOFF ≤ 8 and SGCSCONF CS ≤ 19 in the init sequence."""
    for _name, tag, value in _INIT_SEQ:
        if tag == 0x04:
            assert value & 0x0F <= 8
        if tag == 0x06:
            assert value & 0x1F <= SAFETY_CS_MAX


def test_encode_matches_tmc260c_driver(backend):
    """Backend datagram encoding mirrors Tmc260cDriver.encode_datagram."""
    from src.app.server.services.tmc260c_driver import Tmc260cDriver
    for tag, value in [(0x00, DRVCTRL_DEFAULT), (0x04, 0x99548),
                       (0x06, 0xD3F13), (0x07, 0xEF050)]:
        assert backend._encode(tag, value) == Tmc260cDriver.encode_datagram(tag, value)
