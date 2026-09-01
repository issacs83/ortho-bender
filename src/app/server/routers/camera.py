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

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

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
    Open the camera and transition power_state to 'on'.

    Backend chain, first match wins: native ISI/CSI-2 (`isi_csi2` — the
    bench Alvium C on MIPI), VmbPy (USB Alvium), Vimba X GStreamer,
    generic V4L2 GStreamer, UVC. Idempotent — an already-connected
    camera returns the current status unchanged. Note the server also
    retries this automatically in the background after boot until a
    camera appears.
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
    Gracefully shut the camera down (stream off, buffers released — for
    VmbPy backends via the SDK's native shutdown sequence) and transition
    power_state to 'off'. Safe to call on an already-disconnected camera.
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
    fps: float = Query(
        15.0, ge=1.0, le=50.0,
        description="목표 스트림 레이트. 1-50 fps 로 클램프 (벤치의 "
                    "Alvium C-052m 센서 상한이 ~50 fps; JPEG 인코딩이 "
                    "실효 레이트를 25 fps 근처로 제한).",
    ),
    svc: CameraService = Depends(_camera_service),
) -> StreamingResponse:
    """
    MJPEG HTTP streaming endpoint.

    The response is a multipart/x-mixed-replace stream of JPEG frames.
    Open directly in an <img> tag or use fetch() with streaming:

        <img src="/api/camera/stream?fps=15" />
    """
    if svc._power_state != "on":
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=412,
            content={"success": False, "error": "Camera is offline", "code": "CAMERA_OFFLINE"},
        )

    # Clamp: the bench sensor tops out at ~50 fps and an unbounded value
    # would spin the capture loop; very low values still stream but slowly.
    fps = max(1.0, min(fps, 50.0))
    return StreamingResponse(
        svc.mjpeg_generator(fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# GET/POST /api/camera/controls — full driver control surface
# ---------------------------------------------------------------------------

@router.get("/controls", response_model=ApiResponse)
async def list_camera_controls(
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Enumerate every parameter the connected camera exposes.

    The list is read live from the sensor driver (exposure/gain with
    auto-windows, gamma, black level, flips, binning, the full trigger
    suite, device temperature, firmware/serial, ...) so it always matches
    the attached camera model. Value units are the driver's raw units
    (exposure ns, gain millibel, gamma x100, temperature 0.1 degC).
    """
    try:
        return ok({"controls": await svc.list_controls()})
    except RuntimeError as exc:
        return err(str(exc), "CAMERA_CONTROLS_UNSUPPORTED")


class CameraControlRequest(BaseModel):
    id: int = Field(..., description="GET /controls 가 주는 숫자 컨트롤 id")
    value: int | list[int] = Field(
        0, description="드라이버 원시 단위 값(int), 또는 AREA 형 "
                       "'Binning Setting'(width, height) 같은 복합 "
                       "컨트롤용 int 배열; 버튼 컨트롤에서는 무시")


@router.post("/controls", response_model=ApiResponse)
async def set_camera_control(
    body: CameraControlRequest,
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Set one camera control by id (buttons fire on any write).

    Returns the read-back value so the UI can display what the camera
    actually accepted (values are clamped by the hardware).
    """
    try:
        value = await svc.set_control(body.id, body.value)
        return ok({"id": body.id, "value": value})
    except PermissionError as exc:
        return err(str(exc), "CAMERA_CONTROL_READ_ONLY")
    except (RuntimeError, OSError) as exc:
        return err(str(exc), "CAMERA_CONTROL_ERROR")


# ---------------------------------------------------------------------------
# Camera presets — server-side UserSet substitute
# ---------------------------------------------------------------------------

@router.get("/presets", response_model=ApiResponse)
async def list_camera_presets(
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Named camera presets (all writable controls + ROI + sensor fps).

    Alvium CSI-2 models expose no on-camera UserSet over V4L2, so
    presets are stored server-side and re-applied through the normal
    control paths.
    """
    return ok({"presets": await svc.list_presets()})


class CameraPresetRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64,
                      description="프리셋 이름 (예: 'backlight-wire')")


@router.post("/presets", response_model=ApiResponse)
async def save_camera_preset(
    body: CameraPresetRequest,
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Snapshot the current camera state under the given name."""
    try:
        return ok(await svc.save_preset(body.name))
    except (RuntimeError, OSError) as exc:
        return err(str(exc), "CAMERA_PRESET_ERROR")


@router.post("/presets/{name}/apply", response_model=ApiResponse)
async def apply_camera_preset(
    name: str,
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Apply a saved preset (fps → ROI → controls). Per-item failures are
    reported in `errors` without aborting the rest."""
    try:
        return ok(await svc.apply_preset(name))
    except KeyError as exc:
        return err(str(exc), "CAMERA_PRESET_NOT_FOUND")
    except (RuntimeError, OSError) as exc:
        return err(str(exc), "CAMERA_PRESET_ERROR")


@router.delete("/presets/{name}", response_model=ApiResponse)
async def delete_camera_preset(
    name: str,
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Delete a saved preset."""
    try:
        await svc.delete_preset(name)
        return ok({"deleted": name})
    except KeyError as exc:
        return err(str(exc), "CAMERA_PRESET_NOT_FOUND")


# ---------------------------------------------------------------------------
# GET/POST /api/camera/framerate — sensor acquisition rate
# ---------------------------------------------------------------------------

@router.get("/framerate", response_model=ApiResponse)
async def get_camera_framerate(
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Sensor-side acquisition frame rate (fps).

    Lives on the V4L2 subdev *frame-interval* API — another feature that
    is not part of GET /controls. Lowering it raises the exposure-time
    ceiling; the MJPEG ?fps= parameter only paces delivery.
    """
    try:
        return ok({"fps": await svc.get_sensor_frame_rate()})
    except (RuntimeError, OSError) as exc:
        return err(str(exc), "CAMERA_FRAMERATE_ERROR")


class CameraFramerateRequest(BaseModel):
    fps: float = Field(..., gt=0, le=500, description="목표 센서 fps")


@router.post("/framerate", response_model=ApiResponse)
async def set_camera_framerate(
    body: CameraFramerateRequest,
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Set the sensor acquisition frame rate; returns the applied value."""
    try:
        return ok({"fps": await svc.set_sensor_frame_rate(body.fps)})
    except (RuntimeError, OSError) as exc:
        return err(str(exc), "CAMERA_FRAMERATE_ERROR")


# ---------------------------------------------------------------------------
# GET/POST /api/camera/roi — sensor crop (region of interest)
# ---------------------------------------------------------------------------

@router.get("/roi", response_model=ApiResponse)
async def get_camera_roi(
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Current sensor crop rectangle plus its bounds and default.

    ROI lives on the V4L2 subdev *selection* API (not a control), which
    is why it does not appear in GET /controls.
    """
    try:
        return ok(await svc.get_roi())
    except (RuntimeError, OSError) as exc:
        return err(str(exc), "CAMERA_ROI_ERROR")


class CameraRoiRequest(BaseModel):
    left: int = Field(0, ge=0, description="센서 위 X 오프셋 (px)")
    top: int = Field(0, ge=0, description="센서 위 Y 오프셋 (px)")
    width: int = Field(..., gt=0, description="ROI 폭 (px)")
    height: int = Field(..., gt=0, description="ROI 높이 (px)")


@router.post("/roi", response_model=ApiResponse)
async def set_camera_roi(
    body: CameraRoiRequest,
    svc: CameraService = Depends(_camera_service),
) -> ApiResponse:
    """Apply a sensor crop. The capture/stream restarts at the new size;
    the driver may clamp or align the rectangle — the response carries
    what was actually applied."""
    try:
        return ok(await svc.set_roi(body.left, body.top, body.width, body.height))
    except (RuntimeError, OSError) as exc:
        return err(str(exc), "CAMERA_ROI_ERROR")


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
