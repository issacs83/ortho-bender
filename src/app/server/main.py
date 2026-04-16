"""
main.py — Ortho-Bender SDK FastAPI application entry point.

Startup sequence:
  1. Load settings from environment / .env
  2. Connect IpcClient to RPMsg device (or start in mock mode)
  3. Open camera
  4. Start WebSocket background broadcast tasks
  5. Serve REST API + WebSocket endpoints

Usage::

    # Development (mock hardware):
    OB_MOCK_MODE=true uvicorn server.main:app --reload --port 8000

    # Production (on i.MX8MP):
    OB_MOCK_MODE=false OB_IPC_DEVICE=/dev/rpmsg0 uvicorn server.main:app --host 0.0.0.0 --port 8000

IEC 62304 SW Class: B
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .routers import bending, cam, camera, motor, system, wifi, diag_router
from .services.camera_service import CameraService
from .services.diag_service import DiagService
from .services.ipc_client import IpcClient
from .services.motor_backend import MockMotorBackend
from .services.motor_service import MotorService
from .ws.manager import WsManager

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    log.info("Starting Ortho-Bender SDK (mock=%s)", cfg.mock_mode)

    # IPC client — graceful fallback to mock if M7 is not responding
    ipc_mock = cfg.mock_mode
    ipc = IpcClient(
        device=cfg.ipc_device,
        mock=ipc_mock,
        timeout_s=cfg.ipc_timeout_s,
    )
    try:
        await ipc.connect()
    except (FileNotFoundError, OSError) as exc:
        log.warning("IPC connect failed (%s) — falling back to mock motor", exc)
        ipc = IpcClient(device=cfg.ipc_device, mock=True, timeout_s=cfg.ipc_timeout_s)
        await ipc.connect()
    app.state.ipc_client = ipc

    # Services — camera always uses real hardware when mock_mode=false
    motor_svc  = MotorService(ipc)
    camera_svc = CameraService(mock=cfg.mock_mode)
    await camera_svc.connect()

    app.state.motor_service  = motor_svc
    app.state.camera_service = camera_svc

    # Diagnostic backend — always MockMotorBackend until spidev is implemented
    diag_backend = MockMotorBackend()
    diag_svc = DiagService(diag_backend)
    app.state.diag_service = diag_svc

    # WebSocket manager + background tasks
    ws_manager = WsManager()

    async def _motor_provider():
        try:
            status = await motor_svc.get_status()
            return status.model_dump()
        except Exception:
            return None

    async def _camera_provider():
        try:
            jpeg = await camera_svc.capture_jpeg(quality=cfg.camera_jpeg_quality)
            if not jpeg:
                return None
            return {
                "jpeg":   jpeg,
                "width":  camera_svc._width or 0,
                "height": camera_svc._height or 0,
            }
        except Exception:
            return None

    async def _system_provider():
        try:
            return {
                "ipc_connected":    ipc.connected,
                "camera_connected": camera_svc._connected,
            }
        except Exception:
            return None

    async def _diag_provider():
        try:
            results = {}
            for did in ("tmc260c_0", "tmc260c_1"):
                status = await diag_svc._tmc260c_0.read_status() if did == "tmc260c_0" \
                    else await diag_svc._tmc260c_1.read_status()
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
            return {"drivers": results}
        except Exception:
            return None

    ws_manager.start_background_tasks(
        motor_provider=_motor_provider,
        camera_provider=_camera_provider,
        system_provider=_system_provider,
        diag_provider=_diag_provider,
    )
    app.state.ws_manager = ws_manager

    log.info("Ortho-Bender SDK ready on :%d", cfg.port)
    yield

    # Shutdown
    log.info("Shutting down Ortho-Bender SDK...")
    await ws_manager.stop()
    await camera_svc.disconnect()
    await ipc.disconnect()
    log.info("Shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    cfg = get_settings()

    application = FastAPI(
        title="Ortho-Bender SDK API",
        description=(
            "REST + WebSocket API for the orthodontic wire bending machine (i.MX8MP). "
            "Provides hardware-agnostic control of motor axes, camera, and B-code bending sequences."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS — allow all origins in development; restrict in production via env
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST routers
    application.include_router(motor.router)
    application.include_router(camera.router)
    application.include_router(bending.router)
    application.include_router(cam.router)
    application.include_router(system.router)
    application.include_router(wifi.router)
    application.include_router(diag_router.router)

    # WebSocket endpoints
    @application.websocket("/ws/motor")
    async def ws_motor(ws: WebSocket):
        await application.state.ws_manager.handle_motor(ws)

    @application.websocket("/ws/camera")
    async def ws_camera(ws: WebSocket):
        await application.state.ws_manager.handle_camera(ws)

    @application.websocket("/ws/system")
    async def ws_system(ws: WebSocket):
        await application.state.ws_manager.handle_system(ws)

    @application.websocket("/ws/motor/diag")
    async def ws_motor_diag(ws: WebSocket):
        await application.state.ws_manager.handle_motor_diag(ws)

    # Health probe (used by systemd + load balancers)
    @application.get("/health", tags=["meta"])
    async def health():
        return {"status": "ok"}

    # Static frontend (optional): served at "/" when a built dist is present.
    # API, WebSocket, /health, /docs routers above take precedence because
    # FastAPI matches routes in registration order. html=True enables SPA
    # fallback (missing paths return index.html).
    _frontend_dist = os.environ.get(
        "OB_FRONTEND_DIST", "/opt/ortho-bender/frontend-dist"
    )
    if os.path.isdir(_frontend_dist):
        application.mount(
            "/",
            StaticFiles(directory=_frontend_dist, html=True),
            name="frontend",
        )
        log.info("Frontend dist mounted at / from %s", _frontend_dist)
    else:
        log.info("Frontend dist not found at %s — skipping static mount", _frontend_dist)

    return application


app = create_app()


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run(
        "server.main:app",
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level,
        reload=False,
    )
