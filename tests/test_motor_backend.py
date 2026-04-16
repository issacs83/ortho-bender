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
    result = await mock_backend.spi_transfer(cs=0, data=bytes([0x09, 0x00, 0x00]))
    assert len(result) == 3
    val = (result[0] << 16) | (result[1] << 8) | result[2]
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
    assert mock_backend.positions[0] == 100


@pytest.mark.asyncio
async def test_mock_pulse_step_reverse(mock_backend):
    """Reverse direction decrements position."""
    await mock_backend.pulse_step(axis=0, count=50, freq_hz=200, direction=-1)
    assert mock_backend.positions[0] == -50
