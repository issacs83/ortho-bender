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
