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
