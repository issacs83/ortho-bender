#!/usr/bin/env python3
"""
camera_stream.py — Allied Vision camera access via the Ortho-Bender SDK.

For vision / ML developers who want frames from the Alvium 1800 U-158m
without touching Vimba X, GenICam, or USB3 Vision directly.

Two modes:
  1. One-shot JPEG snapshot via REST    (POST /api/camera/capture)
  2. Live stream via WebSocket          (/ws/camera — base64 JPEG frames)

Requirements:
  pip install httpx websockets pillow
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import time

import httpx


def check(resp: dict) -> dict:
    if not resp.get("success"):
        raise RuntimeError(f"[{resp.get('code')}] {resp.get('error')}")
    return resp["data"]


def snapshot(host: str, out: str) -> None:
    """REST one-shot capture — useful for triggered inspection flows."""
    client = httpx.Client(base_url=host, timeout=10.0)

    status = check(client.get("/api/camera/status").json())
    print(f"camera: {status.get('device_id')}  "
          f"{status.get('width')}x{status.get('height')}  "
          f"backend={status.get('backend')}")

    data = check(client.post("/api/camera/capture",
                             json={"quality": 85}).json())
    jpeg_b64 = data["frame_b64"]
    jpeg = base64.b64decode(jpeg_b64)
    with open(out, "wb") as f:
        f.write(jpeg)
    print(f"saved {len(jpeg)} bytes → {out}")
    client.close()


async def live_stream(host: str, frames: int) -> None:
    """WebSocket streaming — use for real-time inference or GUI display."""
    import websockets   # deferred import so snapshot path doesn't need it

    ws_url = host.replace("http", "ws") + "/ws/camera"
    print(f"connecting to {ws_url}")
    t0 = time.monotonic()
    received = 0
    async with websockets.connect(ws_url, max_size=8 * 1024 * 1024) as ws:
        while received < frames:
            msg = await ws.recv()
            # Frames are JSON envelopes: {type, frame_b64, width, height, timestamp_us}
            import json
            payload = json.loads(msg)
            if payload.get("type") != "camera_frame":
                continue
            received += 1
            dt = time.monotonic() - t0
            fps = received / dt if dt > 0 else 0
            print(f"frame {received:03d}  "
                  f"{payload['width']}x{payload['height']}  "
                  f"~{fps:.1f} fps")
    print(f"received {received} frames in {time.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ortho-Bender camera example")
    parser.add_argument("--host", default="http://localhost:8000")
    parser.add_argument("--mode", choices=["snapshot", "stream"], default="snapshot")
    parser.add_argument("--out", default="frame.jpg")
    parser.add_argument("--frames", type=int, default=30)
    args = parser.parse_args()

    if args.mode == "snapshot":
        snapshot(args.host, args.out)
    else:
        asyncio.run(live_stream(args.host, args.frames))
