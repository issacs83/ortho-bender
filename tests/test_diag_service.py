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
