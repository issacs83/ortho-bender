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
    assert 0 <= response < (1 << 20)


@pytest.mark.asyncio
async def test_write_register_encodes_tag(driver):
    """Register tag appears in bits [19:17] of the datagram."""
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
    await driver.set_current(20)
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
