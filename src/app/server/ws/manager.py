"""
manager.py — WebSocket connection manager.

Manages three independent broadcast channels:
  /ws/motor       — 100 ms motor position/state stream
  /ws/camera      — camera frame stream (JPEG base64)
  /ws/system      — system events (alarms, state changes, heartbeat)
  /ws/motor/diag  — 200 Hz diagnostic stream (JSON or MessagePack binary)

The diagnostic channel supports an optional ``?format=msgpack`` query
parameter.  When a client connects with that parameter, frames are sent as
MessagePack binary instead of JSON text, reducing bandwidth by ~80 %.
All other channels remain JSON-only (backward compatible).

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Callable, Optional

try:
    import msgpack  # type: ignore[import-untyped]
    _MSGPACK_AVAILABLE = True
except ImportError:
    _MSGPACK_AVAILABLE = False

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

log = logging.getLogger(__name__)


class ConnectionSet:
    """Thread-safe set of active WebSocket connections for one channel."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.add(ws)
        log.debug("WS[%s]: client connected (total=%d)", self._name, len(self._connections))

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        log.debug("WS[%s]: client disconnected (total=%d)", self._name, len(self._connections))

    async def broadcast(self, message: str | bytes) -> None:
        """Send to all connected clients; silently drop disconnected ones."""
        async with self._lock:
            dead = set()
            for ws in self._connections:
                try:
                    if ws.client_state == WebSocketState.CONNECTED:
                        if isinstance(message, bytes):
                            await ws.send_bytes(message)
                        else:
                            await ws.send_text(message)
                    else:
                        dead.add(ws)
                except Exception:
                    dead.add(ws)
            self._connections -= dead

    @property
    def count(self) -> int:
        return len(self._connections)


class DiagConnectionSet:
    """
    Format-aware WebSocket connection set for the /ws/motor/diag channel.

    Each connection may request binary MessagePack frames via
    ``?format=msgpack``.  All other connections receive JSON text frames.
    This allows opt-in bandwidth reduction without breaking existing clients.
    """

    def __init__(self) -> None:
        # Maps WebSocket → use_msgpack flag
        self._connections: dict[WebSocket, bool] = {}
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket, use_msgpack: bool = False) -> None:
        async with self._lock:
            self._connections[ws] = use_msgpack
        log.debug(
            "WS[motor_diag]: client connected format=%s (total=%d)",
            "msgpack" if use_msgpack else "json",
            len(self._connections),
        )

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.pop(ws, None)
        log.debug("WS[motor_diag]: client disconnected (total=%d)", len(self._connections))

    async def broadcast(self, payload: dict) -> None:
        """
        Encode *payload* as JSON or MessagePack per-connection and send.

        JSON-encoded connections receive a text frame.
        MessagePack-encoded connections receive a binary frame.
        """
        if not self._connections:
            return

        # Pre-encode both formats lazily (only if there are subscribers for each)
        json_frame: Optional[str] = None
        msgpack_frame: Optional[bytes] = None

        async with self._lock:
            dead: list[WebSocket] = []
            for ws, use_msgpack in self._connections.items():
                try:
                    if ws.client_state != WebSocketState.CONNECTED:
                        dead.append(ws)
                        continue
                    if use_msgpack:
                        if msgpack_frame is None:
                            if not _MSGPACK_AVAILABLE:
                                # Fallback to JSON if msgpack is not installed
                                if json_frame is None:
                                    json_frame = json.dumps(payload)
                                await ws.send_text(json_frame)
                                continue
                            msgpack_frame = msgpack.packb(payload, use_bin_type=True)
                        await ws.send_bytes(msgpack_frame)
                    else:
                        if json_frame is None:
                            json_frame = json.dumps(payload)
                        await ws.send_text(json_frame)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.pop(ws, None)

    @property
    def count(self) -> int:
        return len(self._connections)


class WsManager:
    """
    Central WebSocket manager — one instance per application lifetime.

    Inject via FastAPI dependency::

        def get_ws_manager(request: Request) -> WsManager:
            return request.app.state.ws_manager
    """

    def __init__(self) -> None:
        self.motor  = ConnectionSet("motor")
        self.camera = ConnectionSet("camera")
        self.system = ConnectionSet("system")
        self.motor_diag = DiagConnectionSet()

        self._motor_task:  Optional[asyncio.Task] = None
        self._camera_task: Optional[asyncio.Task] = None
        self._system_task: Optional[asyncio.Task] = None
        self._diag_task:   Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_background_tasks(
        self,
        motor_provider:  Callable,
        camera_provider: Callable,
        system_provider: Callable,
        diag_provider:   Optional[Callable] = None,
        camera_fps:      float = 30.0,
    ) -> None:
        """
        Launch background loops that push data to connected clients.

        Each provider is an async callable that returns the next payload
        dict (or None to skip a cycle).

        :param motor_provider:  async () -> dict | None  (100 ms cadence)
        :param camera_provider: async () -> bytes | None (JPEG)
        :param system_provider: async () -> dict | None  (event-driven)
        :param camera_fps:      camera broadcast frame rate cap (default 30)
        """
        self._camera_fps = camera_fps
        self._motor_task  = asyncio.create_task(
            self._motor_loop(motor_provider),  name="ws_motor_loop"
        )
        self._camera_task = asyncio.create_task(
            self._camera_loop(camera_provider), name="ws_camera_loop"
        )
        self._system_task = asyncio.create_task(
            self._system_loop(system_provider), name="ws_system_loop"
        )
        if diag_provider:
            self._diag_task = asyncio.create_task(
                self._diag_loop(diag_provider), name="ws_diag_loop"
            )
        log.info("WsManager: background broadcast tasks started")

    async def stop(self) -> None:
        for task in (self._motor_task, self._camera_task, self._system_task, self._diag_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        log.info("WsManager: background tasks stopped")

    # ------------------------------------------------------------------
    # WebSocket handlers (call from route handlers)
    # ------------------------------------------------------------------

    async def handle_motor(self, ws: WebSocket) -> None:
        """Handle a single /ws/motor connection until disconnect."""
        await ws.accept()
        await self.motor.add(ws)
        try:
            while True:
                # Keep alive — read loop (client may send pings)
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await self.motor.remove(ws)

    async def handle_camera(self, ws: WebSocket) -> None:
        """Handle a single /ws/camera connection until disconnect."""
        await ws.accept()
        await self.camera.add(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await self.camera.remove(ws)

    async def handle_system(self, ws: WebSocket) -> None:
        """Handle a single /ws/system connection until disconnect."""
        await ws.accept()
        await self.system.add(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await self.system.remove(ws)

    async def handle_motor_diag(self, ws: WebSocket, use_msgpack: bool = False) -> None:
        """
        Handle a single /ws/motor/diag connection until disconnect.

        :param use_msgpack: When True, send binary MessagePack frames instead
                            of JSON text.  Set by the caller when the client
                            requests ``?format=msgpack``.
        """
        await ws.accept()
        await self.motor_diag.add(ws, use_msgpack=use_msgpack)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await self.motor_diag.remove(ws)

    # ------------------------------------------------------------------
    # Broadcast helpers (called externally on events)
    # ------------------------------------------------------------------

    async def broadcast_alarm(self, alarm_code: int, severity: int, message: str) -> None:
        payload = json.dumps({
            "type":       "alarm",
            "alarm_code": alarm_code,
            "severity":   severity,
            "message":    message,
            "timestamp_us": int(time.monotonic() * 1_000_000),
        })
        await self.system.broadcast(payload)

    async def broadcast_state_change(self, new_state: int) -> None:
        payload = json.dumps({
            "type":       "state_change",
            "state":      new_state,
            "message":    f"Motion state changed to {new_state}",
            "timestamp_us": int(time.monotonic() * 1_000_000),
        })
        await self.system.broadcast(payload)

    # ------------------------------------------------------------------
    # Background broadcast loops
    # ------------------------------------------------------------------

    async def _motor_loop(self, provider: Callable) -> None:
        """Broadcast motor status at 100 ms intervals."""
        while True:
            try:
                data = await provider()
                if data is not None and self.motor.count > 0:
                    payload = json.dumps({
                        "type": "motor_status",
                        "timestamp_us": int(time.monotonic() * 1_000_000),
                        **data,
                    })
                    await self.motor.broadcast(payload)
            except Exception as exc:
                log.debug("WS motor loop error: %s", exc)
            await asyncio.sleep(0.1)

    async def _camera_loop(self, provider: Callable) -> None:
        """Broadcast camera frames when clients are connected."""
        fps = getattr(self, '_camera_fps', 30.0)
        interval = 1.0 / max(fps, 1.0)
        while True:
            try:
                if self.camera.count > 0:
                    frame = await provider()
                    if frame:
                        jpeg = frame["jpeg"]
                        payload = json.dumps({
                            "type":       "camera_frame",
                            "frame_b64":  base64.b64encode(jpeg).decode(),
                            "width":      frame.get("width", 0),
                            "height":     frame.get("height", 0),
                            "timestamp_us": int(time.monotonic() * 1_000_000),
                            "meta":       frame.get("meta"),
                        })
                        await self.camera.broadcast(payload)
            except Exception as exc:
                log.debug("WS camera loop error: %s", exc)
            await asyncio.sleep(interval)

    async def _system_loop(self, provider: Callable) -> None:
        """Broadcast system heartbeat every 1 second."""
        while True:
            try:
                data = await provider()
                if data is not None and self.system.count > 0:
                    payload = json.dumps({
                        "type": "heartbeat",
                        "timestamp_us": int(time.monotonic() * 1_000_000),
                        **data,
                    })
                    await self.system.broadcast(payload)
            except Exception as exc:
                log.debug("WS system loop error: %s", exc)
            await asyncio.sleep(1.0)

    async def _diag_loop(self, provider: Callable) -> None:
        """Broadcast diagnostic status at 200 Hz (5 ms intervals).

        Passes the raw dict to DiagConnectionSet.broadcast() which handles
        per-connection serialisation (JSON text or MessagePack binary).
        """
        while True:
            try:
                if self.motor_diag.count > 0:
                    data = await provider()
                    if data is not None:
                        payload: dict = {
                            "type": "diag_status",
                            "timestamp_us": int(time.monotonic() * 1_000_000),
                            **data,
                        }
                        await self.motor_diag.broadcast(payload)
            except Exception as exc:
                log.debug("WS diag loop error: %s", exc)
            await asyncio.sleep(0.005)  # 200 Hz
