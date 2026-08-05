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
    """set_current accepts 0-19 (hard safety cap) and rejects outside."""
    await driver.set_current(19)
    with pytest.raises(ValueError):
        await driver.set_current(20)  # SAFETY_CS_MAX=19 — boards burned at CS=31
    with pytest.raises(ValueError):
        await driver.set_current(-1)


@pytest.mark.asyncio
async def test_set_microstep(driver):
    """set_microstep accepts valid MRES values."""
    await driver.set_microstep(0x04)  # 16 microsteps
    await driver.set_microstep(0x00)  # 256 microsteps


@pytest.mark.asyncio
async def test_set_microstep_preserves_dedge_intpol(mock_backend, driver):
    """set_microstep must keep DEDGE (bit 8) + INTPOL (bit 9) set.

    A regression here halves the step rate: the PWM STEP path relies on
    DEDGE (2 microsteps per PWM cycle).
    """
    captured: list[bytes] = []
    original = mock_backend.spi_transfer

    async def capture(cs, data):
        captured.append(bytes(data))
        return await original(cs, data)

    mock_backend.spi_transfer = capture
    await driver.set_microstep(4)
    datagram = (captured[-1][0] << 16) | (captured[-1][1] << 8) | captured[-1][2]
    assert datagram & (1 << 8), "DEDGE dropped by set_microstep"
    assert datagram & (1 << 9), "INTPOL dropped by set_microstep"
    assert datagram & 0x0F == 4


def test_drvctrl_default_is_1_16_with_dedge():
    """DRVCTRL_DEFAULT: MRES=4 (1/16), DEDGE=1, INTPOL=1."""
    from src.app.server.services.tmc260c_driver import DRVCTRL_DEFAULT
    assert DRVCTRL_DEFAULT & 0x0F == 4
    assert DRVCTRL_DEFAULT & (1 << 8)
    assert DRVCTRL_DEFAULT & (1 << 9)


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


@pytest.mark.asyncio
async def test_dump_registers_drvctrl_matches_written_default(driver):
    """dump must report the DRVCTRL value actually written at init.

    An earlier version reported 0x204 — a value never written to the chip.
    """
    from src.app.server.services.tmc260c_driver import DRVCTRL_DEFAULT
    dump = await driver.dump_registers()
    assert dump['DRVCTRL'] == DRVCTRL_DEFAULT
