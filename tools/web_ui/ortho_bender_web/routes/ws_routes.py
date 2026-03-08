"""
WebSocket endpoint for real-time status streaming at 10Hz.
"""

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..motor.serial_client import client
from ..motor import motor_api
from ..config import STATUS_POLL_HZ

router = APIRouter()


@router.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    await websocket.accept()
    interval = 1.0 / STATUS_POLL_HZ

    try:
        while True:
            t0 = time.monotonic()

            if client.connected:
                try:
                    data = await asyncio.to_thread(motor_api.get_all_status)
                except Exception:
                    data = {"motors": {}, "sensors": {}}
                data["connected"] = True
            else:
                data = {"connected": False, "motors": {}, "sensors": {}}

            data["timestamp"] = time.time()

            # Include B-code execution state
            from .bcode_routes import get_execution_state
            data["bcode"] = get_execution_state()

            await websocket.send_json(data)

            elapsed = time.monotonic() - t0
            sleep_time = max(0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
