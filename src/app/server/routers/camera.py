"""
routers/camera.py — /api/camera/* REST endpoints (20 endpoints).

Feature endpoints: exposure, gain, ROI, pixel format, frame rate,
trigger, temperature, user set. Plus connection, status, capabilities,
capture, and MJPEG streaming.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..models.camera_schemas import (
    ConnectResponse, ExposureRequest, ExposureResponse, FrameRateRequest,
    FrameRateResponse, GainRequest, GainResponse, PixelFormatRequest,
    PixelFormatResponse, RoiRequest, RoiResponse, TemperatureResponse,
    TriggerRequest, TriggerResponse, UserSetResponse, UserSetSlotRequest,
    capabilities_to_schema, exposure_to_response, frame_rate_to_response,
    gain_to_response, pixel_format_to_response, roi_to_response,
    status_to_schema, trigger_to_response, userset_to_response,
)
from ..models.schemas import ApiResponse, err, ok
from ..services.camera_backends import (
    CameraDisconnectedError, CameraError, CameraTimeoutError,
    FeatureNotSupportedError, FeatureOutOfRangeError,
)
from ..services.camera_service import CameraService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/camera", tags=["camera"])


def _svc(request: Request) -> CameraService:
    return request.app.state.camera_service


def _error_response(exc: CameraError) -> JSONResponse:
    """Map CameraError subclass to HTTP response."""
    if isinstance(exc, FeatureNotSupportedError):
        return JSONResponse(status_code=422, content={
            "success": False, "error": str(exc),
            "code": "FEATURE_NOT_SUPPORTED",
            "detail": {"feature": exc.feature.value},
        })
    if isinstance(exc, FeatureOutOfRangeError):
        return JSONResponse(status_code=422, content={
            "success": False, "error": str(exc),
            "code": "FEATURE_OUT_OF_RANGE",
            "detail": {
                "feature": exc.feature.value,
                "requested": exc.requested,
                "range": {"min": exc.valid_range.min, "max": exc.valid_range.max,
                          "step": exc.valid_range.step},
            },
        })
    if isinstance(exc, CameraDisconnectedError):
        return JSONResponse(status_code=412, content={
            "success": False, "error": str(exc),
            "code": "CAMERA_DISCONNECTED",
        })
    if isinstance(exc, CameraTimeoutError):
        return JSONResponse(status_code=504, content={
            "success": False, "error": str(exc),
            "code": "CAMERA_TIMEOUT",
        })
    return JSONResponse(status_code=500, content={
        "success": False, "error": str(exc),
        "code": "CAMERA_INTERNAL_ERROR",
    })


# ---------------------------------------------------------------------------
# Connection & Status (5 endpoints)
# ---------------------------------------------------------------------------

@router.post("/connect", response_model=ApiResponse)
async def camera_connect(svc: CameraService = Depends(_svc)):
    """Connect camera — returns device info and capabilities."""
    try:
        result = await svc.connect()
        return ok(result)
    except CameraError as exc:
        return _error_response(exc)
    except Exception as exc:
        log.error("Camera connect: %s", exc)
        return err(str(exc), "CAMERA_CONNECT_ERROR")


@router.post("/disconnect", response_model=ApiResponse)
async def camera_disconnect(svc: CameraService = Depends(_svc)):
    """Disconnect camera gracefully."""
    try:
        await svc.disconnect()
        return ok({})
    except Exception as exc:
        log.error("Camera disconnect: %s", exc)
        return err(str(exc), "CAMERA_DISCONNECT_ERROR")


@router.get("/status", response_model=ApiResponse)
async def get_camera_status(svc: CameraService = Depends(_svc)):
    """Current camera state including all active feature values."""
    try:
        status = await svc.get_status()
        return ok(status_to_schema(status).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.get("/capabilities", response_model=ApiResponse)
async def get_capabilities(svc: CameraService = Depends(_svc)):
    """Supported features and their metadata (ranges, enums, auto)."""
    try:
        caps = svc.capabilities()
        return ok(caps)
    except CameraError as exc:
        return _error_response(exc)


@router.get("/device-info", response_model=ApiResponse)
async def get_device_info(svc: CameraService = Depends(_svc)):
    """Camera identification: model, serial, firmware, vendor."""
    try:
        return ok(svc.device_info())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Exposure (2 endpoints)
# ---------------------------------------------------------------------------

@router.get("/exposure", response_model=ApiResponse)
async def get_exposure(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_exposure()
        return ok(exposure_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/exposure", response_model=ApiResponse)
async def set_exposure(body: ExposureRequest,
                       svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_exposure(auto=body.auto, time_us=body.time_us)
        return ok(exposure_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Gain (2 endpoints)
# ---------------------------------------------------------------------------

@router.get("/gain", response_model=ApiResponse)
async def get_gain(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_gain()
        return ok(gain_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/gain", response_model=ApiResponse)
async def set_gain(body: GainRequest, svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_gain(auto=body.auto, value_db=body.value_db)
        return ok(gain_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# ROI (3 endpoints)
# ---------------------------------------------------------------------------

@router.get("/roi", response_model=ApiResponse)
async def get_roi(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_roi()
        return ok(roi_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/roi", response_model=ApiResponse)
async def set_roi(body: RoiRequest, svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_roi(
            width=body.width, height=body.height,
            offset_x=body.offset_x, offset_y=body.offset_y,
        )
        return ok(roi_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/roi/center", response_model=ApiResponse)
async def center_roi(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.center_roi()
        return ok(roi_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Pixel Format (2 endpoints)
# ---------------------------------------------------------------------------

@router.get("/pixel-format", response_model=ApiResponse)
async def get_pixel_format(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_pixel_format()
        return ok(pixel_format_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/pixel-format", response_model=ApiResponse)
async def set_pixel_format(body: PixelFormatRequest,
                           svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_pixel_format(format=body.format)
        return ok(pixel_format_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Frame Rate (2 endpoints)
# ---------------------------------------------------------------------------

@router.get("/frame-rate", response_model=ApiResponse)
async def get_frame_rate(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_frame_rate()
        return ok(frame_rate_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/frame-rate", response_model=ApiResponse)
async def set_frame_rate(body: FrameRateRequest,
                         svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_frame_rate(enable=body.enable, value=body.value)
        return ok(frame_rate_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Trigger (3 endpoints)
# ---------------------------------------------------------------------------

@router.get("/trigger", response_model=ApiResponse)
async def get_trigger(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_trigger()
        return ok(trigger_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/trigger", response_model=ApiResponse)
async def set_trigger(body: TriggerRequest,
                      svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_trigger(mode=body.mode, source=body.source)
        return ok(trigger_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/trigger/fire", response_model=ApiResponse)
async def fire_trigger(svc: CameraService = Depends(_svc)):
    try:
        await svc.fire_trigger()
        return ok({})
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Temperature (1 endpoint)
# ---------------------------------------------------------------------------

@router.get("/temperature", response_model=ApiResponse)
async def get_temperature(svc: CameraService = Depends(_svc)):
    try:
        temp = await svc.get_temperature()
        return ok({"value_c": temp})
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# UserSet (4 endpoints)
# ---------------------------------------------------------------------------

@router.get("/user-set", response_model=ApiResponse)
async def get_user_set(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_user_set_info()
        return ok(userset_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/user-set/load", response_model=ApiResponse)
async def load_user_set(body: UserSetSlotRequest,
                        svc: CameraService = Depends(_svc)):
    try:
        await svc.load_user_set(slot=body.slot)
        return ok({})
    except CameraError as exc:
        return _error_response(exc)


@router.post("/user-set/save", response_model=ApiResponse)
async def save_user_set(body: UserSetSlotRequest,
                        svc: CameraService = Depends(_svc)):
    try:
        await svc.save_user_set(slot=body.slot)
        return ok({})
    except CameraError as exc:
        return _error_response(exc)


@router.post("/user-set/default", response_model=ApiResponse)
async def set_default_user_set(body: UserSetSlotRequest,
                               svc: CameraService = Depends(_svc)):
    try:
        await svc.set_default_user_set(slot=body.slot)
        return ok({})
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Frame Capture & Streaming (2 endpoints)
# ---------------------------------------------------------------------------

@router.post("/capture")
async def camera_capture(quality: int = 85,
                         svc: CameraService = Depends(_svc)):
    """Capture a single frame as JPEG."""
    try:
        jpeg = await svc.capture_jpeg(quality=quality)
        return Response(content=jpeg, media_type="image/jpeg")
    except CameraError as exc:
        return _error_response(exc)
    except Exception as exc:
        log.error("Camera capture: %s", exc)
        return JSONResponse(status_code=503, content={
            "success": False, "error": str(exc), "code": "CAMERA_CAPTURE_ERROR",
        })


@router.get("/stream")
async def camera_stream(fps: float = 15.0,
                        svc: CameraService = Depends(_svc)):
    """MJPEG HTTP streaming endpoint."""
    if not svc.is_connected:
        return JSONResponse(status_code=412, content={
            "success": False, "error": "Camera disconnected",
            "code": "CAMERA_DISCONNECTED",
        })

    async def _mjpeg():
        async for frame in svc.stream_frames(fps=fps):
            jpeg = frame.to_jpeg(quality=85)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")

    return StreamingResponse(
        _mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
