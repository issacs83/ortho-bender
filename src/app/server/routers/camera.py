"""
routers/camera.py — /api/camera/* REST endpoints.

Supports:
  - Single JPEG frame capture (returns raw JPEG bytes)
  - MJPEG HTTP streaming
  - Camera settings (exposure, gain, format)
  - Status query

IEC 62304 SW Class: B
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from ..models.schemas import (
    ApiResponse,
    CameraSettingsRequest,
    CameraStatusResponse,
    err,
    ok,
)
from ..services.camera_service import CameraService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/camera", tags=["camera"])


def _camera_service(request: Request) -> CameraService:
    return request.app.state.camera_service


# ---------------------------------------------------------------------------
# GET /api/camera/status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=ApiResponse)
async def get_camera_status(
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Return camera connection status and current settings."""
    status = svc.get_status()
    return ok(status)


# ---------------------------------------------------------------------------
# POST /api/camera/connect
# ---------------------------------------------------------------------------

@router.post("/connect", response_model=ApiResponse)
async def camera_connect(
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """
    Open the camera via the Vimba X SDK (or fallback backend) and transition
    power_state to 'on'. Idempotent — already-connected cameras return
    the current status unchanged.
    """
    try:
        ok_ = await svc.connect()
    except Exception as exc:
        log.error("Camera connect raised: %s", exc)
        return err(str(exc), "CAMERA_CONNECT_ERROR")
    if not ok_:
        return err("Camera connect failed — no backend available", "CAMERA_CONNECT_FAILED")
    return ok(svc.get_status())


# ---------------------------------------------------------------------------
# POST /api/camera/disconnect
# ---------------------------------------------------------------------------

@router.post("/disconnect", response_model=ApiResponse)
async def camera_disconnect(
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """
    Gracefully shut the camera down via the Vimba X SDK native shutdown
    sequence (frame release → camera __exit__ → VmbSystem __exit__) and
    transition power_state to 'off'. Safe to call on an already-disconnected
    camera.
    """
    try:
        await svc.disconnect()
    except Exception as exc:
        log.error("Camera disconnect raised: %s", exc)
        return err(str(exc), "CAMERA_DISCONNECT_ERROR")
    return ok(svc.get_status())


# ---------------------------------------------------------------------------
# POST /api/camera/capture
# ---------------------------------------------------------------------------

@router.post("/capture")
async def camera_capture(
    quality: int = 85,
    svc: CameraService = Depends(_camera_service),
) -> Response:
    """
    Capture a single frame and return it as a JPEG image.

    Returns: image/jpeg binary response.
    quality: JPEG compression quality (1-100, default 85).
    """
    if svc._power_state != "on":
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=412,
            content={"success": False, "error": "Camera is offline", "code": "CAMERA_OFFLINE"},
        )
    try:
        jpeg = await svc.capture_jpeg(quality=quality)
        return Response(content=jpeg, media_type="image/jpeg")
    except RuntimeError as exc:
        log.error("Camera capture failed: %s", exc)
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": str(exc), "code": "CAMERA_CAPTURE_ERROR"},
        )


# ---------------------------------------------------------------------------
# GET /api/camera/stream  (MJPEG)
# ---------------------------------------------------------------------------

@router.get("/stream")
async def camera_stream(
    fps: float = 15.0,
    svc: CameraService = Depends(_camera_service),
) -> StreamingResponse:
    """
    MJPEG HTTP streaming endpoint.

    The response is a multipart/x-mixed-replace stream of JPEG frames.
    Open directly in an <img> tag or use fetch() with streaming:

        <img src="/api/camera/stream" />
    """
    if svc._power_state != "on":
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=412,
            content={"success": False, "error": "Camera is offline", "code": "CAMERA_OFFLINE"},
        )

    return StreamingResponse(
        svc.mjpeg_generator(fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# POST /api/camera/settings
# ---------------------------------------------------------------------------

@router.post("/settings", response_model=ApiResponse)
async def camera_settings(
    body: CameraSettingsRequest,
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Apply camera settings (exposure, gain, pixel format)."""
    if svc._power_state != "on":
        return err("Camera is offline", "CAMERA_OFFLINE")
    try:
        await svc.apply_settings(
            exposure_us=body.exposure_us,
            gain_db=body.gain_db,
            pixel_format=body.format,
        )
        return ok(svc.get_status())
    except Exception as exc:
        log.error("Camera settings failed: %s", exc)
        return err(str(exc), "CAMERA_SETTINGS_ERROR")
