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

import asyncio

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .routers import bending, cam, camera, docs, motor, system, wifi, diag_router
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

    # Services — camera always uses real hardware when mock_mode=false.
    # Camera_service interface evolved (mock=bool → backend=CameraBackend).
    # Try the new backend-injection signature first; fall back to legacy
    # mock=bool, and finally degrade to None if both fail (motor-only mode).
    # MotorService spidev injection happens later, after diag_backend init.
    motor_svc  = MotorService(ipc)
    camera_svc: CameraService | None = None
    try:
        try:
            from .services.camera_backends.auto_backend import AutoCameraBackend  # type: ignore
            camera_svc = CameraService(backend=AutoCameraBackend())  # type: ignore[arg-type]
        except (ImportError, TypeError):
            camera_svc = CameraService(mock=cfg.mock_mode)  # type: ignore[arg-type]
        await camera_svc.connect()
    except Exception as exc:
        log.warning("Camera init failed: %s — continuing without camera", exc)
        camera_svc = None

    # Null-camera fallback so routes that depend on camera.get_status() etc.
    # don't 500 when the camera failed to init (e.g. running on bench
    # without Allied Vision device).
    if camera_svc is None:
        class _NullCameraService:
            _connected = False
            _width = 0
            _height = 0
            is_connected = False
            backend_name = "null"
            device_id: str | None = None
            def get_status(self):
                return {
                    "connected": False, "backend": "mock", "device_id": None,
                    "width": 0, "height": 0, "fps": 0,
                }
            async def capture_jpeg(self, **_kwargs):
                return None
            async def disconnect(self):
                pass
            def __getattr__(self, name):
                # Permissive fallback for any other attribute access.
                # Non-callable -> None/False; callable -> async no-op.
                async def _async_noop(*_a, **_k): return None
                if name.startswith("is_") or name.startswith("has_"):
                    return False
                return _async_noop
        camera_svc = _NullCameraService()  # type: ignore[assignment]
        log.info("Using NullCameraService fallback (no camera attached)")

    app.state.motor_service  = motor_svc
    app.state.camera_service = camera_svc

    # Boot-order resilience: at cold boot this service starts (~9 s) before
    # the avt3 CSI-2 sensor finishes probing (~12 s), so the first connect()
    # finds no camera and the UI would need a manual reconnect. Retry in the
    # background with backoff until the camera appears (also covers camera
    # power applied after boot).
    camera_retry_task = None
    if isinstance(camera_svc, CameraService) and not camera_svc.get_status()["connected"]:
        async def _camera_reconnect_loop():
            delay = 3.0
            while True:
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 30.0)
                try:
                    if await camera_svc.connect():
                        log.info("Camera reconnect loop: camera connected")
                        return
                except Exception as exc:
                    log.debug("Camera reconnect attempt failed: %s", exc)

        camera_retry_task = asyncio.create_task(_camera_reconnect_loop())
        log.info("Camera not present yet — background reconnect loop started")

    # Diagnostic backend — select via OB_MOTOR_BACKEND env var.
    # Verified bench mapping (2026-05-08): cs=0→LIFT, cs=1→BEND, cs=2→FEED.
    if cfg.motor_backend == "spidev":
        from .services.spi_backend import SpidevMotorBackend
        diag_backend = SpidevMotorBackend(
            spi_device=cfg.spi_device,
            spi_speed_hz=cfg.spi_speed_hz,
            gpio_lift_cs=cfg.gpio_lift_cs,
            gpio_bend_cs=cfg.gpio_bend_cs,
            gpio_feed_cs=cfg.gpio_feed_cs,
            gpio_dir=cfg.gpio_dir,
            pwm_step_path=cfg.pwm_step_path,
            pwm_step_export=cfg.pwm_step_export,
            gpio_limit_lift=cfg.gpio_limit_lift,
            gpio_limit_bend=cfg.gpio_limit_bend,
        )
        await diag_backend.open()
        # Wire spidev backend into MotorService so REST move/jog drive the
        # bench directly (instead of dispatching IPC to a non-existent M7).
        motor_svc._spi_backend = diag_backend
        log.info("MotorService bench mode enabled via SpidevMotorBackend")
    else:
        diag_backend = MockMotorBackend()
    diag_svc = DiagService(diag_backend)
    # PSU preset is persisted on disk and consulted by DiagService when a
    # raw register write touches SGCSCONF — so the operator's choice in
    # Settings caps the driver current even if the frontend is bypassed.
    from .services.psu_service import PsuService
    psu_svc = PsuService()
    diag_svc.set_psu_service(psu_svc)
    app.state.psu_service = psu_svc
    app.state.diag_service = diag_svc
    # Propagate the PSU cap into the bench backend so _init_chip writes a
    # supply-appropriate SGCSCONF (not the unconditional CS=19 default).
    if hasattr(diag_backend, "apply_current_cap"):
        diag_backend.apply_current_cap(psu_svc.cs_cap)
    # Gravity-axis idle holding (LIFT = cs0 sinks when de-energized)
    if hasattr(diag_backend, "hold_axes") and cfg.hold_lift:
        diag_backend.hold_axes = {0}
        diag_backend.hold_cs = int(cfg.hold_cs)
    # Limit guard: LIFT only — BEND's multi-slot disc would trip it
    # at every slot passage (rotary axis has no travel ends anyway).
    if hasattr(diag_backend, "guard_axes"):
        diag_backend.guard_axes = {0}
    # Direction conventions: LIFT (cs 0) "+ is down"; FEED (cs 2) was
    # wired mirrored to BEND, so + / ▶ means clockwise on every axis.
    if hasattr(diag_backend, "invert_axes"):
        inverted = set()
        if cfg.invert_lift:
            inverted.add(0)
        if cfg.invert_feed:
            inverted.add(2)
        diag_backend.invert_axes = inverted
        log.info("Axis DIR inversion active for cs=%s", sorted(inverted))
    log.info("PsuService active: %s (cs_cap=%d)", psu_svc.psu.label, psu_svc.cs_cap)

    # Per-axis steps/unit calibration so jog/move convert mm/deg → step rate
    # using the actual mechanical ratios. Defaults match the legacy "200
    # microsteps = 1 unit" behaviour but are overridable from Settings.
    from .services.motion_profiles import MotionProfileService
    mp_svc = MotionProfileService()
    motor_svc.set_motion_profiles(mp_svc)
    app.state.motion_profiles = mp_svc
    from .services.calibration_service import CalibrationService
    cal_svc = CalibrationService()
    motor_svc.set_calibration(cal_svc)
    app.state.calibration_service = cal_svc
    log.info("CalibrationService active: %s", cal_svc.all()["steps_per_unit"])

    # Probe motor drivers at startup — identify which chips are connected
    driver_probe = await diag_svc.probe_drivers()
    app.state.driver_probe = {r.driver: r.model_dump() for r in driver_probe}
    connected_count = sum(1 for r in driver_probe if r.connected)
    log.info("Driver probe complete: %d/%d connected", connected_count, len(driver_probe))

    # WebSocket manager + background tasks
    ws_manager = WsManager()

    async def _motor_provider():
        try:
            status = await motor_svc.get_status()
            return status.model_dump()
        except Exception:
            return None

    async def _camera_provider():
        if camera_svc is None:
            return None
        try:
            jpeg = await camera_svc.capture_jpeg(quality=cfg.camera_jpeg_quality)
            if not jpeg:
                return None
            return {
                "jpeg":   jpeg,
                "width":  getattr(camera_svc, "_width", 0) or 0,
                "height": getattr(camera_svc, "_height", 0) or 0,
            }
        except Exception:
            return None

    async def _system_provider():
        try:
            return {
                "ipc_connected":    ipc.connected,
                "camera_connected": (camera_svc is not None and getattr(camera_svc, "_connected", False)),
                "driver_probe":     app.state.driver_probe,
            }
        except Exception:
            return None

    async def _diag_provider():
        try:
            return await diag_svc.get_live_status()
        except Exception:
            return None

    ws_manager.start_background_tasks(
        motor_provider=_motor_provider,
        camera_provider=_camera_provider,
        system_provider=_system_provider,
        diag_provider=_diag_provider,
        camera_fps=cfg.camera_fps,
    )
    app.state.ws_manager = ws_manager

    log.info("Ortho-Bender SDK ready on :%d", cfg.port)
    yield

    # Shutdown
    log.info("Shutting down Ortho-Bender SDK...")
    if camera_retry_task is not None and not camera_retry_task.done():
        camera_retry_task.cancel()
    await ws_manager.stop()
    if camera_svc is not None:
        try:
            await camera_svc.disconnect()
        except Exception:
            pass
    await ipc.disconnect()
    log.info("Shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    cfg = get_settings()

    # Disable built-in docs — we serve custom routes with local assets (offline)
    application = FastAPI(
        title="Ortho-Bender SDK API",
        description=(
            "REST + WebSocket API for the orthodontic wire bending machine (i.MX8MP).\n\n"
            "**Motor**: 3-axis bench control with hard safety caps (CS ≤ 19, "
            "TOFF 1–8, PSU-derived clamps) and TMC260C register diagnostics.\n\n"
            "**Axis conventions — read before sending coordinates**: "
            "`0=FEED` rotary **deg**, `1=BEND` rotary **deg**, `2=ROTATE` (not "
            "fitted on this bench), `3=LIFT` linear **mm** whose **`+` is DOWN** "
            "(datum 0 at the top limit switch, bottom at +230 mm). `+` is "
            "clockwise on every rotary axis. Calibration: BEND 23.0167 steps/deg "
            "(1 rev = 8286 steps), LIFT 200 steps/mm (230 mm stroke), FEED 200 "
            "steps/deg (placeholder, not yet verified).\n\n"
            "`POST /move` is **relative**, `POST /move_to` is **absolute** and "
            "splits long moves automatically; ramps finish inside the commanded "
            "target (45° lands on 45°, measured error ≤ 0.24° / 0.00 mm). "
            "`/home` runs limit-switch homing (BEND rotary one-rev sweep, LIFT "
            "full-stroke sweep to the top switch) and returns immediately — poll "
            "`/limits`. `/protection` toggles the mid-motion limit guard and the "
            "LIFT holding torque; `/profiles` carries per-axis speed, physical "
            "accel/decel and trapezoidal vs S-curve ramps.\n\n"
            "**Camera**: Allied Vision Alvium 1800 C on MIPI CSI-2 via the native "
            "`isi_csi2` backend — JPEG capture, MJPEG streaming (`?fps=1..50`), the "
            "full dynamic control surface (`/api/camera/controls`), sensor ROI "
            "(`/roi`), and sensor frame rate (`/framerate`). USB Alvium (VmbPy) "
            "remains as a fallback backend.\n\n"
            "**Bending**: B-code sequence execution with background progress "
            "reporting, plus WebSocket telemetry channels (`/ws/motor`, "
            "`/ws/camera`, `/ws/system`, `/ws/motor/diag`)."
        ),
        version="0.3.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "camera",
             "description": "Alvium CSI-2 카메라 — 캡처/스트림/설정, 전체 컨트롤 "
                            "표면(/controls), 센서 ROI(/roi)와 프레임레이트(/framerate). "
                            "ROI·프레임레이트는 V4L2 컨트롤이 아닌 별도 subdev API라 "
                            "/controls 목록에 없다."},
            {"name": "motor",
             "description": "3축 벤치 모터 제어. **축별 단위가 다릅니다**: "
                            "FEED·BEND=deg(+=시계방향), LIFT=mm(**+=아래**, 홈=최상단 0). "
                            "/move=상대, /move_to=절대(긴 이동 자동 분할, 가감속이 "
                            "지정 위치 안에서 완결). /home=리밋 스위치 호밍(즉시 반환, "
                            "/limits로 완료 확인), /protection=리밋 자동정지·LIFT 정지토크, "
                            "/profiles=속도·물리단위 가감속·S-curve, /calibration=steps per unit. "
                            "안전 상한(CS≤19, TOFF 1–8)은 서버가 강제."},
            {"name": "cam",
             "description": "CAD/CAM 진입점 — 3D 와이어 중심선(폴리라인)을 B-code로 "
                            "변환(/generate, 모션 없음·프리뷰 안전)하거나 변환 후 즉시 "
                            "실행(/execute). 재질별 스프링백 보정 포함."},
            {"name": "bending", "description": "B-code 벤딩 시퀀스 실행/진행률/정지. "
                                               "스텝 = Feed(L_mm) → Rotate(beta_deg) → "
                                               "Bend(theta_deg). ROTATE 축 미장착이라 "
                                               "현재 beta_deg는 모션으로 이어지지 않음."},
            {"name": "system", "description": "시스템 상태, PSU 프리셋, 재부팅."},
            {"name": "docs", "description": "오프라인 문서(md) 서빙."},
        ],
    )

    # Serve Swagger/ReDoc assets locally (no CDN dependency — works offline)
    from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html

    _static_dir = os.path.join(os.path.dirname(__file__), "static")
    _has_local = os.path.isdir(_static_dir)
    if _has_local:
        application.mount(
            "/static-api",
            StaticFiles(directory=_static_dir),
            name="api-static",
        )

    _sw_js = "/static-api/swagger-ui/swagger-ui-bundle.js" if _has_local else "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"
    _sw_css = "/static-api/swagger-ui/swagger-ui.css" if _has_local else "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
    _rd_js = "/static-api/redoc/redoc.standalone.js" if _has_local else "https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js"

    @application.get("/docs", include_in_schema=False)
    async def swagger_ui():
        return get_swagger_ui_html(
            openapi_url=application.openapi_url,
            title=application.title + " — Swagger UI",
            swagger_js_url=_sw_js,
            swagger_css_url=_sw_css,
        )

    @application.get("/redoc", include_in_schema=False)
    async def redoc_ui():
        return get_redoc_html(
            openapi_url=application.openapi_url,
            title=application.title + " — ReDoc",
            redoc_js_url=_rd_js,
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
    application.include_router(docs.router)

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
