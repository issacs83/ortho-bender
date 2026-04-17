# Camera Backend ABC + REST API Design Spec

## Goal

Hardware-abstracted camera control SDK that exposes all camera features as vendor-neutral REST API endpoints. SW developers can control the camera without knowing what hardware is underneath. When the camera hardware changes (Allied Vision → Basler → FLIR), the API stays the same, existing code continues to work unchanged.

## Architecture

```
SW Developer (REST API / WebSocket / Python SDK)
         │
    ┌────▼────┐
    │  Router  │  /api/camera/*  (FastAPI)
    └────┬────┘
    ┌────▼──────────┐
    │ CameraService  │  Orchestration (lock, error mapping, streaming lifecycle)
    └────┬──────────┘
    ┌────▼──────────────┐
    │  CameraBackend ABC │  Domain contract (hardware-agnostic)
    ├───────────────────┤
    │ VmbPyCameraBackend │  Allied Vision Alvium (Phase 1)
    │ MockCameraBackend  │  Dev/CI synthetic frames
    │ (future) Pylon     │  Basler
    │ (future) OpenCV    │  Generic UVC
    └───────────────────┘
```

**Dependency Injection:** `main.py` selects backend via `OB_CAMERA_BACKEND` env var → injects into `CameraService` → router extracts from `app.state`.

---

## 1. Data Models

### 1.1 Core Types

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

class Feature(str, Enum):
    EXPOSURE     = "exposure"
    GAIN         = "gain"
    ROI          = "roi"
    PIXEL_FORMAT = "pixel_format"
    FRAME_RATE   = "frame_rate"
    TRIGGER      = "trigger"
    TEMPERATURE  = "temperature"
    USER_SET     = "user_set"

@dataclass(frozen=True)
class NumericRange:
    min: float
    max: float
    step: float = 1.0

@dataclass(frozen=True)
class DeviceInfo:
    model: str           # "Alvium 1800 U-158m"
    serial: str          # "DEV_1AB22D00xxxx"
    firmware: str        # "1.2.3"
    vendor: str          # "Allied Vision"

@dataclass
class FrameMeta:
    """Telemetry attached to every frame."""
    timestamp_us: int
    exposure_us: float
    gain_db: float
    temperature_c: Optional[float]
    fps_actual: float
    width: int
    height: int

@dataclass
class CapturedFrame:
    array: np.ndarray        # Raw sensor data (HxW for mono, HxWxC for color)
    pixel_format: str        # "mono8", "mono12", "bayer_rg8", etc.
    meta: FrameMeta

    def to_jpeg(self, quality: int = 85) -> bytes:
        """Encode to JPEG on demand. Returns JPEG byte string."""
        import cv2
        if self.array.ndim == 2:
            img = self.array
        else:
            img = cv2.cvtColor(self.array, cv2.COLOR_RGB2BGR)
        _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()

@dataclass
class CameraStatus:
    connected: bool
    streaming: bool
    device: Optional[DeviceInfo]
    current_exposure_us: Optional[float]
    current_gain_db: Optional[float]
    current_temperature_c: Optional[float]
    current_fps: Optional[float]
    current_pixel_format: Optional[str]
    current_roi: Optional[dict]  # {width, height, offset_x, offset_y}
    current_trigger_mode: Optional[str]
```

### 1.2 Feature Response Types

Every setter returns a typed response that includes the current value, valid range, and invalidated features.

```python
@dataclass
class ExposureInfo:
    auto: bool
    time_us: float
    range: NumericRange
    auto_available: bool
    invalidated: list[Feature] = field(default_factory=list)

@dataclass
class GainInfo:
    auto: bool
    value_db: float
    range: NumericRange
    auto_available: bool
    invalidated: list[Feature] = field(default_factory=list)

@dataclass
class RoiInfo:
    width: int
    height: int
    offset_x: int
    offset_y: int
    width_range: NumericRange
    height_range: NumericRange
    offset_x_range: NumericRange
    offset_y_range: NumericRange
    invalidated: list[Feature] = field(default_factory=list)

@dataclass
class PixelFormatInfo:
    format: str
    available: list[str]       # ["mono8", "mono10", "mono12", "bayer_rg8", ...]
    invalidated: list[Feature] = field(default_factory=list)

@dataclass
class FrameRateInfo:
    enable: bool
    value: float
    range: NumericRange
    invalidated: list[Feature] = field(default_factory=list)

@dataclass
class TriggerInfo:
    mode: str                  # "freerun", "software", "external"
    source: Optional[str]      # "Software", "Line0", ...
    available_modes: list[str]
    available_sources: list[str]
    invalidated: list[Feature] = field(default_factory=list)

@dataclass
class UserSetInfo:
    current_slot: str
    available_slots: list[str] # ["Default", "UserSet1", "UserSet2", "UserSet3"]
    default_slot: str
```

### 1.3 Capability Descriptor

Returned by `GET /api/camera/capabilities` and included in `POST /api/camera/connect` response.

```python
@dataclass
class FeatureCapability:
    supported: bool
    # Present for numeric features:
    range: Optional[NumericRange] = None
    auto_available: Optional[bool] = None
    # Present for enum features:
    available_values: Optional[list[str]] = None
    # Present for user_set:
    slots: Optional[list[str]] = None
```

Capabilities response is `dict[Feature, FeatureCapability]`.

---

## 2. Error Hierarchy

```python
class CameraError(Exception):
    """Base error for all camera operations."""
    pass

class FeatureNotSupportedError(CameraError):
    """Camera backend does not support this feature."""
    def __init__(self, feature: Feature):
        self.feature = feature
        super().__init__(f"Feature not supported: {feature.value}")

class FeatureOutOfRangeError(CameraError):
    """Requested value is outside the valid range."""
    def __init__(self, feature: Feature, requested: float, valid_range: NumericRange):
        self.feature = feature
        self.requested = requested
        self.valid_range = valid_range
        super().__init__(
            f"{feature.value}: {requested} is out of range "
            f"[{valid_range.min}, {valid_range.max}]"
        )

class CameraDisconnectedError(CameraError):
    """Operation attempted on a disconnected camera."""
    pass

class CameraTimeoutError(CameraError):
    """Camera operation timed out (frame capture, feature write, etc.)."""
    pass
```

### Error → HTTP Status Mapping

| Exception | HTTP Status | Error Code |
|-----------|-------------|------------|
| `FeatureNotSupportedError` | 422 | `FEATURE_NOT_SUPPORTED` |
| `FeatureOutOfRangeError` | 422 | `FEATURE_OUT_OF_RANGE` |
| `CameraDisconnectedError` | 412 | `CAMERA_DISCONNECTED` |
| `CameraTimeoutError` | 504 | `CAMERA_TIMEOUT` |
| Unexpected exception | 500 | `CAMERA_INTERNAL_ERROR` |

Error response body always includes context:

```json
{
  "success": false,
  "error": "Value out of range",
  "code": "FEATURE_OUT_OF_RANGE",
  "detail": {
    "feature": "exposure",
    "requested": 999999999,
    "range": { "min": 20, "max": 10000000, "step": 1 }
  }
}
```

---

## 3. CameraBackend ABC

```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Optional

class CameraBackend(ABC):
    """Hardware-abstracted camera interface.

    Lifecycle: connect() → use → disconnect()
    Context manager supported: async with backend as cam: ...

    Thread safety: NOT thread-safe.
    Single owner — one coroutine controls the camera at a time.
    Use asyncio.Lock externally (CameraService provides this).

    State precondition: all feature methods require connected state.
    Calling any method before connect() raises CameraDisconnectedError.
    """

    # --- Context Manager ---

    async def __aenter__(self) -> "CameraBackend":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.disconnect()

    # --- Required: every backend MUST implement these ---

    @abstractmethod
    async def connect(self) -> DeviceInfo:
        """Open camera and return device info. Idempotent."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully shut down. Safe to call multiple times."""
        ...

    @abstractmethod
    async def capture(self) -> CapturedFrame:
        """Capture a single frame with telemetry metadata."""
        ...

    @abstractmethod
    async def stream(self, fps: float = 30.0) -> AsyncIterator[CapturedFrame]:
        """Continuous frame stream. Break from async for to stop.
        Cleanup is automatic on generator exit."""
        ...

    @abstractmethod
    def capabilities(self) -> dict[Feature, FeatureCapability]:
        """Supported features + metadata (ranges, enums, auto support).
        Call once after connect() to build UI / validate inputs."""
        ...

    @abstractmethod
    async def get_status(self) -> CameraStatus:
        """Current camera state including all active feature values."""
        ...

    @abstractmethod
    def device_info(self) -> DeviceInfo:
        """Return device info obtained during connect(). No hardware call."""
        ...

    # --- Optional: default raises FeatureNotSupportedError ---

    # Exposure
    async def set_exposure(self, *, auto: bool = False,
                           time_us: Optional[float] = None) -> ExposureInfo:
        raise FeatureNotSupportedError(Feature.EXPOSURE)

    async def get_exposure(self) -> ExposureInfo:
        raise FeatureNotSupportedError(Feature.EXPOSURE)

    # Gain
    async def set_gain(self, *, auto: bool = False,
                       value_db: Optional[float] = None) -> GainInfo:
        raise FeatureNotSupportedError(Feature.GAIN)

    async def get_gain(self) -> GainInfo:
        raise FeatureNotSupportedError(Feature.GAIN)

    # ROI
    async def set_roi(self, *, width: int, height: int,
                      offset_x: int = 0, offset_y: int = 0) -> RoiInfo:
        raise FeatureNotSupportedError(Feature.ROI)

    async def get_roi(self) -> RoiInfo:
        raise FeatureNotSupportedError(Feature.ROI)

    async def center_roi(self) -> RoiInfo:
        raise FeatureNotSupportedError(Feature.ROI)

    # Pixel Format
    async def set_pixel_format(self, *, format: str) -> PixelFormatInfo:
        raise FeatureNotSupportedError(Feature.PIXEL_FORMAT)

    async def get_pixel_format(self) -> PixelFormatInfo:
        raise FeatureNotSupportedError(Feature.PIXEL_FORMAT)

    # Frame Rate
    async def set_frame_rate(self, *, enable: bool,
                             value: Optional[float] = None) -> FrameRateInfo:
        raise FeatureNotSupportedError(Feature.FRAME_RATE)

    async def get_frame_rate(self) -> FrameRateInfo:
        raise FeatureNotSupportedError(Feature.FRAME_RATE)

    # Trigger
    async def set_trigger(self, *, mode: str,
                          source: Optional[str] = None) -> TriggerInfo:
        raise FeatureNotSupportedError(Feature.TRIGGER)

    async def get_trigger(self) -> TriggerInfo:
        raise FeatureNotSupportedError(Feature.TRIGGER)

    async def fire_trigger(self) -> None:
        raise FeatureNotSupportedError(Feature.TRIGGER)

    # Temperature
    async def get_temperature(self) -> float:
        raise FeatureNotSupportedError(Feature.TEMPERATURE)

    # UserSet
    async def load_user_set(self, *, slot: str) -> None:
        raise FeatureNotSupportedError(Feature.USER_SET)

    async def save_user_set(self, *, slot: str) -> None:
        raise FeatureNotSupportedError(Feature.USER_SET)

    async def set_default_user_set(self, *, slot: str) -> None:
        raise FeatureNotSupportedError(Feature.USER_SET)

    async def get_user_set_info(self) -> UserSetInfo:
        raise FeatureNotSupportedError(Feature.USER_SET)
```

---

## 4. REST API Endpoints

Base path: `/api/camera`

All responses follow the envelope: `{ "success": bool, "data"?: T, "error"?: str, "code"?: str, "detail"?: {} }`

### 4.1 Connection & Status

| Method | Path | Request Body | Response `data` |
|--------|------|-------------|-----------------|
| POST | `/connect` | — | `{ "device": DeviceInfo, "capabilities": dict }` |
| POST | `/disconnect` | — | — |
| GET | `/status` | — | `CameraStatus` |
| GET | `/capabilities` | — | `dict[Feature, FeatureCapability]` |
| GET | `/device-info` | — | `DeviceInfo` |

`POST /connect` returns capabilities together so the client needs only one call to start.

### 4.2 Exposure

| Method | Path | Request Body | Response `data` |
|--------|------|-------------|-----------------|
| GET | `/exposure` | — | `ExposureInfo` |
| POST | `/exposure` | `{ "auto": bool, "time_us"?: float }` | `ExposureInfo` |

When `auto: true`, `time_us` is ignored. The returned `ExposureInfo.time_us` shows the current auto-determined value.

### 4.3 Gain

| Method | Path | Request Body | Response `data` |
|--------|------|-------------|-----------------|
| GET | `/gain` | — | `GainInfo` |
| POST | `/gain` | `{ "auto": bool, "value_db"?: float }` | `GainInfo` |

### 4.4 ROI

| Method | Path | Request Body | Response `data` |
|--------|------|-------------|-----------------|
| GET | `/roi` | — | `RoiInfo` |
| POST | `/roi` | `{ "width": int, "height": int, "offset_x"?: int, "offset_y"?: int }` | `RoiInfo` |
| POST | `/roi/center` | — | `RoiInfo` |

`offset_x` and `offset_y` default to 0. `/roi/center` calculates center offsets for current width/height.

ROI changes may invalidate `frame_rate` (smaller ROI → higher max FPS).

### 4.5 Pixel Format

| Method | Path | Request Body | Response `data` |
|--------|------|-------------|-----------------|
| GET | `/pixel-format` | — | `PixelFormatInfo` |
| POST | `/pixel-format` | `{ "format": str }` | `PixelFormatInfo` |

Format strings: `"mono8"`, `"mono10"`, `"mono12"`, `"bayer_rg8"`, `"bayer_rg10"`, `"bayer_rg12"`, `"rgb8"`.

Pixel format changes may invalidate `frame_rate`.

### 4.6 Frame Rate

| Method | Path | Request Body | Response `data` |
|--------|------|-------------|-----------------|
| GET | `/frame-rate` | — | `FrameRateInfo` |
| POST | `/frame-rate` | `{ "enable": bool, "value"?: float }` | `FrameRateInfo` |

When `enable: false`, the camera runs at maximum achievable frame rate for the current ROI and pixel format.

### 4.7 Trigger

| Method | Path | Request Body | Response `data` |
|--------|------|-------------|-----------------|
| GET | `/trigger` | — | `TriggerInfo` |
| POST | `/trigger` | `{ "mode": str, "source"?: str }` | `TriggerInfo` |
| POST | `/trigger/fire` | — | — |

Modes: `"freerun"`, `"software"`, `"external"`. `/trigger/fire` executes a software trigger (only valid when mode is `"software"`).

### 4.8 Temperature

| Method | Path | Response `data` |
|--------|------|-----------------|
| GET | `/temperature` | `{ "value_c": float }` |

Read-only. No setter.

### 4.9 UserSet

| Method | Path | Request Body | Response `data` |
|--------|------|-------------|-----------------|
| GET | `/user-set` | — | `UserSetInfo` |
| POST | `/user-set/load` | `{ "slot": str }` | — |
| POST | `/user-set/save` | `{ "slot": str }` | — |
| POST | `/user-set/default` | `{ "slot": str }` | — |

Slots: `"Default"`, `"UserSet1"`, `"UserSet2"`, `"UserSet3"`.

### 4.10 Frame Capture & Streaming

| Method | Path | Params | Response |
|--------|------|--------|----------|
| POST | `/capture` | `?quality=85` | `image/jpeg` binary |
| GET | `/stream` | `?fps=15` | `multipart/x-mixed-replace` MJPEG |
| WS | `/ws/camera` | — | Binary frames + JSON FrameMeta |

WebSocket frame message format:
```json
{
  "type": "frame",
  "jpeg_b64": "<base64 encoded JPEG>",
  "meta": {
    "timestamp_us": 1713400000000,
    "exposure_us": 5000,
    "gain_db": 6.2,
    "temperature_c": 42.3,
    "fps_actual": 29.97,
    "width": 1456,
    "height": 1088
  }
}
```

Every frame carries live telemetry — no separate polling needed during streaming. When not streaming, use `GET /status` at 1 Hz for monitoring.

---

## 5. Backend Implementations

### 5.1 VmbPyCameraBackend

First production implementation targeting Allied Vision Alvium 1800 U-158m.

**GenICam Node Mapping (internal, never exposed to API):**

| ABC Method | GenICam Node(s) |
|-----------|-----------------|
| `set_exposure(time_us=)` | `ExposureTime.set(value)` |
| `set_exposure(auto=True)` | `ExposureAuto.set("Continuous")` |
| `set_gain(value_db=)` | `Gain.set(value)` |
| `set_gain(auto=True)` | `GainAuto.set("Continuous")` |
| `set_roi(w, h, ox, oy)` | `Width`, `Height`, `OffsetX`, `OffsetY` |
| `center_roi()` | Calculate offsets from `WidthMax`, `HeightMax` |
| `set_pixel_format(fmt)` | `PixelFormat.set(mapped_enum)` |
| `set_frame_rate(enable, val)` | `AcquisitionFrameRateEnable`, `AcquisitionFrameRate` |
| `set_trigger(mode, source)` | `TriggerMode`, `TriggerSource` |
| `fire_trigger()` | `TriggerSoftware.run()` |
| `get_temperature()` | `DeviceTemperature.get()` |
| `load_user_set(slot)` | `UserSetSelector.set()`, `UserSetLoad.run()` |
| `save_user_set(slot)` | `UserSetSelector.set()`, `UserSetSave.run()` |
| `set_default_user_set(slot)` | `UserSetDefault.set()` |

**Range queries:** Each numeric feature calls `feature.get_range()` → `(min, max, step)` from VmbPy. Enum features call `feature.get_available_entries()`.

**Hot/cold handling:** ROI and PixelFormat changes internally stop acquisition, apply the change, and restart. This is transparent to the caller. The stream resumes automatically — the frontend sees at most a 100-200ms gap.

**Invalidation rules:**

| Changed Feature | Invalidates |
|----------------|-------------|
| ROI (width/height) | `frame_rate` |
| Pixel Format | `frame_rate` |
| Trigger Mode | `frame_rate` |

**Thread model:** All VmbPy calls are blocking → wrapped in `asyncio.loop.run_in_executor(None, ...)`.

### 5.2 MockCameraBackend

Development and CI backend. No real camera needed.

- Generates synthetic gradient frames (numpy) with configurable resolution
- All 8 features fully simulated with realistic ranges
- Auto exposure/gain simulation: value converges over 10 frames toward a target
- Temperature simulation: slowly increases from 35°C to 45°C, resets on disconnect
- UserSet: in-memory dict storage of feature snapshots
- `capabilities()` returns all features as supported
- `stream()` yields frames at requested FPS using `asyncio.sleep()`

Default ranges match Alvium 1800 U-158m specs so frontend dev matches production behavior.

---

## 6. CameraService (Orchestration Layer)

Thin layer between router and backend. Responsibilities:

1. **asyncio.Lock** — serializes concurrent access to the backend
2. **Error mapping** — catches `CameraError` subclasses, converts to HTTP responses
3. **Streaming lifecycle** — manages active stream state, prevents multiple simultaneous streams
4. **JPEG encoding** — calls `CapturedFrame.to_jpeg()` for REST capture endpoint
5. **Backend selection** — receives injected `CameraBackend` instance

```python
class CameraService:
    def __init__(self, backend: CameraBackend) -> None:
        self._backend = backend
        self._lock = asyncio.Lock()
        self._streaming = False

    async def connect(self) -> dict:
        async with self._lock:
            device = await self._backend.connect()
            caps = self._backend.capabilities()
            return {"device": device, "capabilities": caps}

    async def set_exposure(self, auto: bool, time_us: float | None) -> ExposureInfo:
        async with self._lock:
            return await self._backend.set_exposure(auto=auto, time_us=time_us)

    # ... same pattern for all feature methods
```

### main.py Integration

```python
# Backend selection via OB_CAMERA_BACKEND env var
if cfg.camera_backend == "vmbpy":
    camera_backend = VmbPyCameraBackend()
else:
    camera_backend = MockCameraBackend()

camera_svc = CameraService(camera_backend)
app.state.camera_service = camera_svc
```

---

## 7. WebSocket Frame Metadata

Extend existing `/ws/camera` to include `FrameMeta` with every frame.

Current behavior: sends JPEG base64 frames only.
New behavior: sends JPEG base64 + metadata dict.

The `_camera_provider` in `main.py` changes from returning just `jpeg` to returning `CapturedFrame`, and the WS serializer includes `meta`.

When not streaming (camera connected but idle), `GET /api/camera/status` polled at 1 Hz provides the same telemetry data.

---

## 8. Frontend Integration

### 8.1 client.ts Extensions

Add to `cameraApi`:

```typescript
interface CameraCapabilities {
  exposure?: { supported: boolean; range?: NumericRange; auto_available?: boolean };
  gain?: { supported: boolean; range?: NumericRange; auto_available?: boolean };
  roi?: { supported: boolean; width_range?: NumericRange; height_range?: NumericRange };
  // ... etc
}

cameraApi = {
  // Existing (signature updated)
  connect: () => Promise<{ device: DeviceInfo; capabilities: CameraCapabilities }>,
  status: () => Promise<CameraStatus>,

  // New feature endpoints
  capabilities: () => Promise<CameraCapabilities>,
  getExposure: () => Promise<ExposureInfo>,
  setExposure: (params: { auto: boolean; time_us?: number }) => Promise<ExposureInfo>,
  getGain: () => Promise<GainInfo>,
  setGain: (params: { auto: boolean; value_db?: number }) => Promise<GainInfo>,
  getRoi: () => Promise<RoiInfo>,
  setRoi: (params: { width: number; height: number; offset_x?: number; offset_y?: number }) => Promise<RoiInfo>,
  centerRoi: () => Promise<RoiInfo>,
  getPixelFormat: () => Promise<PixelFormatInfo>,
  setPixelFormat: (params: { format: string }) => Promise<PixelFormatInfo>,
  getFrameRate: () => Promise<FrameRateInfo>,
  setFrameRate: (params: { enable: boolean; value?: number }) => Promise<FrameRateInfo>,
  getTrigger: () => Promise<TriggerInfo>,
  setTrigger: (params: { mode: string; source?: string }) => Promise<TriggerInfo>,
  fireTrigger: () => Promise<void>,
  getTemperature: () => Promise<{ value_c: number }>,
  getUserSet: () => Promise<UserSetInfo>,
  loadUserSet: (params: { slot: string }) => Promise<void>,
  saveUserSet: (params: { slot: string }) => Promise<void>,
  setDefaultUserSet: (params: { slot: string }) => Promise<void>,
};
```

### 8.2 CameraPage Changes

- On camera connect: call `connect()`, receive capabilities, build UI dynamically
- Hide unsupported feature widgets (based on `capabilities.*.supported`)
- After any POST: check `invalidated` array, re-fetch affected features
- Status Strip: show connection status, streaming state, FPS, temperature from WS FrameMeta
- Apply-on-commit pattern: numeric inputs fire API call on Enter/blur, not on every keystroke
- Debounce slider inputs: 100ms

---

## 9. Example Code

Delivered in `examples/camera/`, each file is self-contained and runnable.

### 01_connect_and_capture.py

```python
"""Connect to camera and capture a single frame."""
import requests

BASE = "http://192.168.4.1:8000"

# Connect — returns device info and capabilities
r = requests.post(f"{BASE}/api/camera/connect")
data = r.json()["data"]
print(f"Connected: {data['device']['vendor']} {data['device']['model']}")
print(f"Supported features: {[k for k, v in data['capabilities'].items() if v['supported']]}")

# Capture single frame as JPEG
r = requests.post(f"{BASE}/api/camera/capture", params={"quality": 90})
with open("frame.jpg", "wb") as f:
    f.write(r.content)
print("Saved frame.jpg")

# Disconnect
requests.post(f"{BASE}/api/camera/disconnect")
```

### 02_exposure_gain_control.py

```python
"""Control exposure and gain — manual and auto modes."""
import requests

BASE = "http://192.168.4.1:8000"
requests.post(f"{BASE}/api/camera/connect")

# Check valid range
r = requests.get(f"{BASE}/api/camera/exposure")
info = r.json()["data"]
print(f"Exposure range: {info['range']['min']}–{info['range']['max']} μs")

# Set manual exposure
r = requests.post(f"{BASE}/api/camera/exposure", json={"auto": False, "time_us": 10000})
print(f"Exposure set to: {r.json()['data']['time_us']} μs")

# Switch to auto exposure
r = requests.post(f"{BASE}/api/camera/exposure", json={"auto": True})
print(f"Auto exposure — current value: {r.json()['data']['time_us']} μs")

# Set manual gain
r = requests.post(f"{BASE}/api/camera/gain", json={"auto": False, "value_db": 6.0})
print(f"Gain set to: {r.json()['data']['value_db']} dB")

requests.post(f"{BASE}/api/camera/disconnect")
```

### 03_roi_and_format.py

```python
"""Set ROI and pixel format."""
import requests

BASE = "http://192.168.4.1:8000"
requests.post(f"{BASE}/api/camera/connect")

# Set ROI to center 800x600
r = requests.post(f"{BASE}/api/camera/roi", json={"width": 800, "height": 600})
data = r.json()["data"]
print(f"ROI: {data['width']}x{data['height']} at ({data['offset_x']},{data['offset_y']})")

# Check if frame_rate was invalidated
if "frame_rate" in data.get("invalidated", []):
    r = requests.get(f"{BASE}/api/camera/frame-rate")
    print(f"New max FPS: {r.json()['data']['range']['max']}")

# Center the ROI
r = requests.post(f"{BASE}/api/camera/roi/center")
data = r.json()["data"]
print(f"Centered at ({data['offset_x']},{data['offset_y']})")

# Change pixel format
r = requests.post(f"{BASE}/api/camera/pixel-format", json={"format": "mono12"})
print(f"Format: {r.json()['data']['format']}")

requests.post(f"{BASE}/api/camera/disconnect")
```

### 04_trigger_software.py

```python
"""Software trigger mode — capture on demand."""
import requests, time

BASE = "http://192.168.4.1:8000"
requests.post(f"{BASE}/api/camera/connect")

# Set software trigger mode
requests.post(f"{BASE}/api/camera/trigger", json={"mode": "software"})
print("Software trigger mode active")

# Fire trigger and capture
for i in range(5):
    requests.post(f"{BASE}/api/camera/trigger/fire")
    r = requests.post(f"{BASE}/api/camera/capture")
    with open(f"triggered_{i}.jpg", "wb") as f:
        f.write(r.content)
    print(f"Captured triggered_{i}.jpg")
    time.sleep(0.5)

# Return to freerun
requests.post(f"{BASE}/api/camera/trigger", json={"mode": "freerun"})
requests.post(f"{BASE}/api/camera/disconnect")
```

### 05_continuous_stream.py

```python
"""Continuous MJPEG stream — display FPS from frame metadata."""
import requests, json, time

BASE = "http://192.168.4.1:8000"
requests.post(f"{BASE}/api/camera/connect")

# Stream via WebSocket (using websocket-client)
import websocket
ws = websocket.create_connection(f"ws://192.168.4.1:8000/ws/camera")

start = time.time()
frame_count = 0
try:
    while time.time() - start < 10:  # Stream for 10 seconds
        msg = json.loads(ws.recv())
        meta = msg["meta"]
        frame_count += 1
        if frame_count % 30 == 0:
            print(f"FPS: {meta['fps_actual']:.1f}  "
                  f"Exp: {meta['exposure_us']:.0f}μs  "
                  f"Temp: {meta['temperature_c']:.1f}°C")
finally:
    ws.close()
    print(f"\nReceived {frame_count} frames in 10s")

requests.post(f"{BASE}/api/camera/disconnect")
```

### 06_opencv_processing.py

```python
"""Capture frame and process with OpenCV."""
import requests, numpy as np, cv2

BASE = "http://192.168.4.1:8000"
requests.post(f"{BASE}/api/camera/connect")

# Capture JPEG, decode to numpy
r = requests.post(f"{BASE}/api/camera/capture")
arr = np.frombuffer(r.content, dtype=np.uint8)
img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
print(f"Frame shape: {img.shape}")

# Edge detection
edges = cv2.Canny(img, 100, 200)
cv2.imwrite("edges.jpg", edges)
print("Saved edges.jpg")

# Threshold
_, binary = cv2.threshold(img, 128, 255, cv2.THRESH_BINARY)
cv2.imwrite("binary.jpg", binary)
print("Saved binary.jpg")

# Histogram
hist = cv2.calcHist([img], [0], None, [256], [0, 256])
print(f"Mean intensity: {img.mean():.1f}, Std: {img.std():.1f}")

requests.post(f"{BASE}/api/camera/disconnect")
```

### 07_userset_save_restore.py

```python
"""Save and restore camera settings via UserSet."""
import requests

BASE = "http://192.168.4.1:8000"
requests.post(f"{BASE}/api/camera/connect")

# Configure camera
requests.post(f"{BASE}/api/camera/exposure", json={"auto": False, "time_us": 8000})
requests.post(f"{BASE}/api/camera/gain", json={"auto": False, "value_db": 3.0})
requests.post(f"{BASE}/api/camera/roi", json={"width": 1024, "height": 768})
print("Settings configured")

# Save to UserSet1
requests.post(f"{BASE}/api/camera/user-set/save", json={"slot": "UserSet1"})
print("Saved to UserSet1")

# Change settings
requests.post(f"{BASE}/api/camera/exposure", json={"auto": False, "time_us": 1000})
print("Changed exposure to 1000 μs")

# Restore from UserSet1
requests.post(f"{BASE}/api/camera/user-set/load", json={"slot": "UserSet1"})
r = requests.get(f"{BASE}/api/camera/exposure")
print(f"Restored exposure: {r.json()['data']['time_us']} μs")  # → 8000

# Set as default (auto-load on power up)
requests.post(f"{BASE}/api/camera/user-set/default", json={"slot": "UserSet1"})
print("UserSet1 set as power-on default")

requests.post(f"{BASE}/api/camera/disconnect")
```

### 08_full_inspection_pipeline.py

```python
"""Full inspection pipeline: connect → configure → capture → process → save."""
import requests, numpy as np, cv2, json, time

BASE = "http://192.168.4.1:8000"

# 1. Connect and inspect capabilities
r = requests.post(f"{BASE}/api/camera/connect")
caps = r.json()["data"]["capabilities"]
device = r.json()["data"]["device"]
print(f"Camera: {device['vendor']} {device['model']}")

# 2. Configure for inspection
requests.post(f"{BASE}/api/camera/roi", json={"width": 1200, "height": 900})
requests.post(f"{BASE}/api/camera/roi/center")
requests.post(f"{BASE}/api/camera/exposure", json={"auto": False, "time_us": 5000})
requests.post(f"{BASE}/api/camera/gain", json={"auto": False, "value_db": 0})
if caps.get("pixel_format", {}).get("supported"):
    requests.post(f"{BASE}/api/camera/pixel-format", json={"format": "mono8"})
print("Camera configured for inspection")

# 3. Capture and process
r = requests.post(f"{BASE}/api/camera/capture", params={"quality": 95})
arr = np.frombuffer(r.content, dtype=np.uint8)
img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)

# Simple wire detection (example)
blurred = cv2.GaussianBlur(img, (5, 5), 0)
edges = cv2.Canny(blurred, 50, 150)
lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50,
                         minLineLength=100, maxLineGap=10)
print(f"Detected {len(lines) if lines is not None else 0} line segments")

# 4. Save results
cv2.imwrite("inspection_raw.jpg", img)
cv2.imwrite("inspection_edges.jpg", edges)

# Draw detected lines
result = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
if lines is not None:
    for line in lines:
        x1, y1, x2, y2 = line[0]
        cv2.line(result, (x1, y1), (x2, y2), (0, 255, 0), 2)
cv2.imwrite("inspection_result.jpg", result)
print("Results saved")

# 5. Check temperature
if caps.get("temperature", {}).get("supported"):
    r = requests.get(f"{BASE}/api/camera/temperature")
    print(f"Camera temperature: {r.json()['data']['value_c']}°C")

requests.post(f"{BASE}/api/camera/disconnect")
```

---

## 10. File Structure

```
src/app/server/
├── services/
│   ├── camera_backends/
│   │   ├── __init__.py          # ABC, data models, errors, Feature enum
│   │   ├── vmbpy_backend.py     # VmbPyCameraBackend
│   │   └── mock_backend.py      # MockCameraBackend
│   └── camera_service.py        # CameraService (orchestration, refactored)
├── routers/
│   └── camera.py                # 20 endpoints (refactored)
├── models/
│   └── schemas.py               # Pydantic request/response models (extended)
└── main.py                      # Backend selection + DI (updated)

src/app/frontend/
├── src/api/
│   └── client.ts                # cameraApi extensions
└── src/pages/
    └── CameraPage.tsx           # Capabilities-driven dynamic UI

examples/camera/
├── 01_connect_and_capture.py
├── 02_exposure_gain_control.py
├── 03_roi_and_format.py
├── 04_trigger_software.py
├── 05_continuous_stream.py
├── 06_opencv_processing.py
├── 07_userset_save_restore.py
└── 08_full_inspection_pipeline.py
```

---

## 11. Acceptance Criteria

1. All 8 Phase 1 features controllable at runtime via REST API
2. `POST /connect` returns capabilities — single call to configure UI
3. Feature changes return updated range + `invalidated` hints
4. `CapturedFrame.array` is numpy.ndarray — compatible with OpenCV, OpenCL, NPU
5. WebSocket frames include FrameMeta telemetry
6. Mock backend simulates all features — dev works without real camera
7. VmbPy backend handles hot/cold features transparently
8. Error responses include context (range, feature name)
9. 8 example scripts run successfully against mock backend
10. Swagger UI (`/docs`) documents all 20 endpoints with schemas
11. Existing `/api/camera/capture` and `/api/camera/stream` remain backward-compatible

---

## 12. Out of Scope (Phase 2/3)

- Strobe I/O, Bandwidth Limit, Black Level, Gamma, Sharpening (Phase 2)
- Binning/Decimation, LUT, Sequencer (Phase 3)
- Multi-camera simultaneous control
- Frame recording/playback
- OpenCV/NPU processing pipeline abstraction (numpy frames are the universal handoff)
- Light/dark theme for CameraPage UI (uses existing Tailwind tokens)

---

## 13. Design Principles

| Principle | Application |
|-----------|-------------|
| HW Abstraction | Camera swap → zero API/code change |
| Domain ABC | No GenICam node names in API — domain methods only |
| Typed Contract | All responses are dataclass/Pydantic — no untyped dicts |
| Error Context | 4 exception types with range/feature info |
| Frame = numpy | OpenCV / OpenCL / NPU / 3D — all compatible |
| Invalidated hints | Feature dependencies communicated to frontend |
| Examples first | 8 runnable samples — copy-paste and go |
| Single owner | asyncio.Lock in CameraService, no concurrent writes |
| Transparent hot/cold | Backend handles acquisition stop/restart internally |
