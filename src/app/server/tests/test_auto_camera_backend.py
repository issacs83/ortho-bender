"""
test_auto_camera_backend.py -- Unit tests for AutoCameraBackend.

Covers:
  - VID -> sub-backend selection
  - Hot-plug transitions (connect / disconnect / swap)
  - WS event payload shape
  - capture() raising CameraDisconnectedError when no camera is present
  - capture() marking the sub-backend gone when it raises disconnect

All tests use fake scan functions and fake sub-backends -- no real USB.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Optional

import numpy as np
import pytest

from server.services.camera_backends import (
    CameraBackend,
    CameraDisconnectedError,
    CameraStatus,
    CapturedFrame,
    DeviceInfo,
    Feature,
    FeatureCapability,
    FrameMeta,
    NumericRange,
)
from server.services.camera_backends.auto_backend import (
    AutoCameraBackend,
    _VENDOR_MAP,
    _pick_desired_vid,
)


# ---------------------------------------------------------------------------
# Fake sub-backend used by all tests
# ---------------------------------------------------------------------------

class _FakeBackend(CameraBackend):
    """Minimal CameraBackend that records calls and can simulate loss."""

    instances: list["_FakeBackend"] = []

    def __init__(self, vid: int, model: str) -> None:
        self._vid = vid
        self._model = model
        self._device = DeviceInfo(
            model=model,
            serial=f"SN-{vid:04x}",
            firmware="0.0.0",
            vendor="Fake",
        )
        self._connected = False
        self._capture_raises_disconnect = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.capture_calls = 0
        _FakeBackend.instances.append(self)

    async def connect(self) -> DeviceInfo:
        self.connect_calls += 1
        self._connected = True
        return self._device

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def capture(self) -> CapturedFrame:
        self.capture_calls += 1
        if self._capture_raises_disconnect:
            raise CameraDisconnectedError("simulated unplug")
        arr = np.zeros((8, 8), dtype=np.uint8)
        meta = FrameMeta(
            timestamp_us=0, exposure_us=1000.0, gain_db=0.0,
            temperature_c=30.0, fps_actual=30.0, width=8, height=8,
        )
        return CapturedFrame(array=arr, pixel_format="mono8", meta=meta)

    async def stream(self, fps: float = 30.0) -> AsyncIterator[CapturedFrame]:
        yield await self.capture()

    def capabilities(self) -> dict[Feature, FeatureCapability]:
        return {
            Feature.EXPOSURE: FeatureCapability(
                supported=True,
                range=NumericRange(min=0, max=1, step=1),
            ),
        }

    async def get_status(self) -> CameraStatus:
        return CameraStatus(
            connected=self._connected,
            streaming=False,
            device=self._device if self._connected else None,
            current_exposure_us=1000.0,
            current_gain_db=0.0,
            current_temperature_c=30.0,
            current_fps=30.0,
            current_pixel_format="mono8",
            current_roi=None,
            current_trigger_mode="freerun",
        )

    def device_info(self) -> DeviceInfo:
        return self._device

    @property
    def is_connected(self) -> bool:
        return self._connected


@pytest.fixture(autouse=True)
def _reset_fake_instances():
    _FakeBackend.instances.clear()
    yield
    _FakeBackend.instances.clear()


def _make_factory():
    """Produce a backend factory backed by _FakeBackend."""
    def _factory(vid: int) -> Optional[CameraBackend]:
        name, model = _VENDOR_MAP[vid]
        return _FakeBackend(vid=vid, model=f"{model}-{name}")
    return _factory


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, ev: dict) -> None:
        self.events.append(ev)


# ---------------------------------------------------------------------------
# Helpers that don't need a backend instance
# ---------------------------------------------------------------------------

def test_vendor_map_contains_expected_vendors():
    assert 0x1AB2 in _VENDOR_MAP          # Allied Vision
    assert 0x2B00 in _VENDOR_MAP           # NOVITEC
    assert _VENDOR_MAP[0x1AB2][0] == "vmbpy"
    assert _VENDOR_MAP[0x2B00][0] == "novitec"


def test_pick_desired_vid_priority():
    # Alvium wins over NOVITEC when both are present.
    assert _pick_desired_vid({0x1AB2, 0x2B00}) == 0x1AB2
    # NOVITEC alone.
    assert _pick_desired_vid({0x2B00, 0x1234}) == 0x2B00
    # Unknown devices only.
    assert _pick_desired_vid({0x1234, 0xABCD}) is None
    # Nothing on the bus.
    assert _pick_desired_vid(set()) is None


# ---------------------------------------------------------------------------
# Empty bus -> no activation, capture() raises
# ---------------------------------------------------------------------------

async def test_no_camera_capture_raises_disconnected():
    scanned = {"value": set()}

    def _scan() -> set[int]:
        return scanned["value"]

    recorder = _EventRecorder()
    auto = AutoCameraBackend(
        ws_event_callback=recorder,
        scan_interval=0.01,
        scan_fn=_scan,
        backend_factory=_make_factory(),
    )
    info = await auto.connect()
    assert info.model == ""           # blank placeholder
    assert info.serial == ""
    assert auto.is_connected is False
    assert auto.active_backend_name is None
    assert auto.capabilities() == {}
    with pytest.raises(CameraDisconnectedError):
        await auto.capture()
    status = await auto.get_status()
    assert status.connected is False
    await auto.disconnect()
    assert recorder.events == []      # never connected, no events


# ---------------------------------------------------------------------------
# Plug -> connect event + sub-backend activation
# ---------------------------------------------------------------------------

async def test_plug_emits_connected_event_and_activates_backend():
    scanned = {"value": {0x1AB2}}    # Alvium present from the start

    def _scan() -> set[int]:
        return scanned["value"]

    recorder = _EventRecorder()
    auto = AutoCameraBackend(
        ws_event_callback=recorder,
        scan_interval=0.01,
        scan_fn=_scan,
        backend_factory=_make_factory(),
    )
    info = await auto.connect()
    assert info.model.startswith("Alvium")
    assert auto.is_connected is True
    assert auto.active_backend_name == "vmbpy"
    assert auto.active_vid == 0x1AB2
    assert recorder.events[-1]["type"] == "camera_connected"
    assert recorder.events[-1]["vid_hex"] == "0x1ab2"
    assert recorder.events[-1]["backend"] == "vmbpy"
    assert recorder.events[-1]["serial"] == "SN-1ab2"

    # Real capture should succeed while active.
    frame = await auto.capture()
    assert frame.pixel_format == "mono8"
    assert auto.capabilities()           # non-empty
    await auto.disconnect()


# ---------------------------------------------------------------------------
# Hot-swap: Alvium -> NOVITEC triggers disconnect + reconnect events
# ---------------------------------------------------------------------------

async def test_hot_swap_between_alvium_and_novitec():
    scanned = {"value": {0x1AB2}}

    def _scan() -> set[int]:
        return scanned["value"]

    recorder = _EventRecorder()
    auto = AutoCameraBackend(
        ws_event_callback=recorder,
        scan_interval=0.01,
        scan_fn=_scan,
        backend_factory=_make_factory(),
    )
    await auto.connect()
    assert auto.active_backend_name == "vmbpy"

    # Unplug Alvium, plug NOVITEC.
    scanned["value"] = {0x2B00}
    await auto._run_scan_once()          # deterministic single transition

    assert auto.active_backend_name == "novitec"
    assert auto.active_vid == 0x2B00

    types = [ev["type"] for ev in recorder.events]
    # Must contain at least: connect(Alvium), disconnect(Alvium), connect(Novitec)
    assert types.count("camera_connected") >= 2
    assert types.count("camera_disconnected") >= 1
    # Last event should be the new device coming online.
    assert recorder.events[-1]["type"] == "camera_connected"
    assert recorder.events[-1]["vid_hex"] == "0x2b00"
    assert recorder.events[-1]["backend"] == "novitec"

    await auto.disconnect()


# ---------------------------------------------------------------------------
# Unplug -> disconnect event + capture raises
# ---------------------------------------------------------------------------

async def test_unplug_emits_disconnect_and_capture_raises():
    scanned = {"value": {0x2B00}}

    def _scan() -> set[int]:
        return scanned["value"]

    recorder = _EventRecorder()
    auto = AutoCameraBackend(
        ws_event_callback=recorder,
        scan_interval=0.01,
        scan_fn=_scan,
        backend_factory=_make_factory(),
    )
    await auto.connect()
    assert auto.active_backend_name == "novitec"
    assert auto.is_connected is True

    # Pull the plug.
    scanned["value"] = set()
    await auto._run_scan_once()

    assert auto.active_backend_name is None
    assert auto.is_connected is False
    assert any(ev["type"] == "camera_disconnected" for ev in recorder.events)
    with pytest.raises(CameraDisconnectedError):
        await auto.capture()

    await auto.disconnect()


# ---------------------------------------------------------------------------
# Sub-backend raises disconnect during capture -> AutoCamera recovers
# ---------------------------------------------------------------------------

async def test_capture_disconnect_during_call_clears_active():
    scanned = {"value": {0x2B00}}

    def _scan() -> set[int]:
        return scanned["value"]

    recorder = _EventRecorder()
    auto = AutoCameraBackend(
        ws_event_callback=recorder,
        scan_interval=0.01,
        scan_fn=_scan,
        backend_factory=_make_factory(),
    )
    await auto.connect()
    assert auto.is_connected is True

    # Simulate a runtime USB error from inside the sub-backend.
    inst = _FakeBackend.instances[-1]
    inst._capture_raises_disconnect = True

    with pytest.raises(CameraDisconnectedError):
        await auto.capture()

    # AutoCameraBackend should have torn down the active backend and emitted
    # a camera_disconnected event so the UI can react.
    assert auto.active_backend_name is None
    assert any(ev["type"] == "camera_disconnected" for ev in recorder.events)

    await auto.disconnect()


# ---------------------------------------------------------------------------
# Alvium takes priority when both cameras are attached simultaneously
# ---------------------------------------------------------------------------

async def test_priority_prefers_alvium_over_novitec():
    scanned = {"value": {0x1AB2, 0x2B00}}

    def _scan() -> set[int]:
        return scanned["value"]

    recorder = _EventRecorder()
    auto = AutoCameraBackend(
        ws_event_callback=recorder,
        scan_interval=0.01,
        scan_fn=_scan,
        backend_factory=_make_factory(),
    )
    await auto.connect()
    assert auto.active_vid == 0x1AB2
    assert auto.active_backend_name == "vmbpy"
    await auto.disconnect()


# ---------------------------------------------------------------------------
# Factory returns None (backend deps missing) -> AutoCamera remains disconnected
# ---------------------------------------------------------------------------

async def test_factory_returning_none_keeps_disconnected():
    scanned = {"value": {0x1AB2}}

    def _scan() -> set[int]:
        return scanned["value"]

    def _null_factory(vid: int) -> Optional[CameraBackend]:
        return None  # simulate missing vmbpy / libusb

    recorder = _EventRecorder()
    auto = AutoCameraBackend(
        ws_event_callback=recorder,
        scan_interval=0.01,
        scan_fn=_scan,
        backend_factory=_null_factory,
    )
    info = await auto.connect()
    assert info.model == ""
    assert auto.is_connected is False
    # No events emitted because nothing ever came up.
    assert recorder.events == []
    await auto.disconnect()


# ---------------------------------------------------------------------------
# Scan loop keeps running after a scan_fn exception
# ---------------------------------------------------------------------------

async def test_scan_loop_survives_scan_exception():
    state = {"raise": True, "vids": {0x2B00}}

    def _flaky_scan() -> set[int]:
        if state["raise"]:
            state["raise"] = False
            raise RuntimeError("transient usb error")
        return state["vids"]

    recorder = _EventRecorder()
    auto = AutoCameraBackend(
        ws_event_callback=recorder,
        scan_interval=0.05,
        scan_fn=_flaky_scan,
        backend_factory=_make_factory(),
    )
    await auto.connect()           # first scan will swallow the RuntimeError
    # Next scan should succeed and pick up NOVITEC.
    await auto._run_scan_once()
    assert auto.active_backend_name == "novitec"
    await auto.disconnect()


# ---------------------------------------------------------------------------
# ws_event_callback exceptions must not crash the scan loop
# ---------------------------------------------------------------------------

async def test_ws_callback_exception_is_swallowed():
    scanned = {"value": {0x2B00}}

    def _scan() -> set[int]:
        return scanned["value"]

    async def _bad_cb(_ev: dict) -> None:
        raise RuntimeError("ws broken")

    auto = AutoCameraBackend(
        ws_event_callback=_bad_cb,
        scan_interval=0.01,
        scan_fn=_scan,
        backend_factory=_make_factory(),
    )
    # Must not raise despite the broken callback.
    info = await auto.connect()
    assert info.model.startswith("u-Nova2")
    assert auto.is_connected is True
    await auto.disconnect()
