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
    try:
        jpeg = await svc.capture_jpeg(quality=quality)
        return Response(content=jpeg, media_type="image/jpeg")
    except RuntimeError as exc:
        log.error("Camera capture failed: %s", exc)
        # Return JSON error wrapped in a 503 instead of raising HTTPException
        # so the client gets a consistent error envelope
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
    if not svc._connected:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": "Camera not connected", "code": "CAMERA_OFFLINE"},
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
