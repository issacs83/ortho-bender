"""Continuous MJPEG stream — display FPS from frame metadata."""
import json
import os
import time

import requests
import websocket

BASE = os.environ.get("OB_API_BASE", "http://192.168.4.1:8000")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")
requests.post(f"{BASE}/api/camera/connect")

# Stream via WebSocket (using websocket-client)
ws = websocket.create_connection(f"{WS_BASE}/ws/camera")

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
