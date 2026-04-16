"""
manager.py — WebSocket connection manager.

Manages three independent broadcast channels:
  /ws/motor   — 100 ms motor position/state stream
  /ws/camera  — camera frame stream (JPEG base64)
  /ws/system  — system events (alarms, state changes, heartbeat)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Callable, Optional

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
        self.motor_diag = ConnectionSet("motor_diag")

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
    ) -> None:
        """
        Launch background loops that push data to connected clients.

        Each provider is an async callable that returns the next payload
        dict (or None to skip a cycle).

        :param motor_provider:  async () -> dict | None  (100 ms cadence)
        :param camera_provider: async () -> bytes | None (JPEG, ~15 fps)
        :param system_provider: async () -> dict | None  (event-driven)
        """
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

    async def handle_motor_diag(self, ws: WebSocket) -> None:
        """Handle a single /ws/motor/diag connection until disconnect."""
        await ws.accept()
        await self.motor_diag.add(ws)
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
        """Broadcast camera frames at ~15 fps when clients are connected."""
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
                        })
                        await self.camera.broadcast(payload)
            except Exception as exc:
                log.debug("WS camera loop error: %s", exc)
            await asyncio.sleep(1.0 / 15)  # ~15 fps cap

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
        """Broadcast diagnostic status at 200 Hz (5 ms intervals)."""
        while True:
            try:
                if self.motor_diag.count > 0:
                    data = await provider()
                    if data is not None:
                        payload = json.dumps({
                            "type": "diag_status",
                            "timestamp_us": int(time.monotonic() * 1_000_000),
                            **data,
                        })
                        await self.motor_diag.broadcast(payload)
            except Exception as exc:
                log.debug("WS diag loop error: %s", exc)
            await asyncio.sleep(0.005)  # 200 Hz
