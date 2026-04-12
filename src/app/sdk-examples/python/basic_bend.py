#!/usr/bin/env python3
"""
basic_bend.py — Minimal Python example for the Ortho-Bender SDK REST API.

Demonstrates:
  1. Query system status
  2. Home all axes
  3. Execute a simple 3-step SS 304 wire bending sequence
  4. Poll bending progress until complete
  5. Print final motor positions

Requirements:
  pip install httpx

Usage:
  # Against local mock server
  python basic_bend.py --host http://localhost:8000

  # Against real hardware on i.MX8MP
  python basic_bend.py --host http://192.168.1.100:8000
"""

from __future__ import annotations

import argparse
import time

import httpx


def check(resp: dict) -> dict:
    """Unwrap the API envelope or raise on error."""
    if not resp.get("success"):
        raise RuntimeError(f"[{resp.get('code')}] {resp.get('error')}")
    return resp["data"]


def main(host: str) -> None:
    client = httpx.Client(base_url=host, timeout=10.0)

    # 1. System status
    print("=== System Status ===")
    status = check(client.get("/api/system/status").json())
    print(f"  SDK version  : {status['sdk_version']}")
    print(f"  IPC connected: {status['ipc_connected']}")
    print(f"  M7 heartbeat : {status['m7_heartbeat_ok']}")
    print(f"  Motion state : {status['motion_state']}")

    # 2. Home all axes
    print("\n=== Homing (axis_mask=0 → all) ===")
    motor = check(client.post("/api/motor/home", json={"axis_mask": 0}).json())
    print(f"  State after home: {motor['state']}")

    # 3. Execute bending sequence
    # Wire: SS 304, 0.457 mm (0.018 inch) — typical lower arch archwire
    steps = [
        {"L_mm": 10.0, "beta_deg": 0.0,   "theta_deg": 30.0},
        {"L_mm": 15.0, "beta_deg": 90.0,  "theta_deg": 45.0},
        {"L_mm": 20.0, "beta_deg": -90.0, "theta_deg": 60.0},
    ]

    print("\n=== Executing 3-step bending sequence ===")
    result = check(client.post("/api/bending/execute", json={
        "steps":            steps,
        "material":         0,      # SS_304
        "wire_diameter_mm": 0.457,
    }).json())
    print(f"  Dispatched {result['total_steps']} steps")

    # 4. Poll progress
    print("\n=== Polling progress ===")
    while True:
        bending = check(client.get("/api/bending/status").json())
        print(f"  Step {bending['current_step']}/{bending['total_steps']} "
              f"({bending['progress_pct']:.1f}%) running={bending['running']}")
        if not bending["running"]:
            break
        time.sleep(0.2)

    # 5. Final motor positions
    print("\n=== Final Motor Positions ===")
    motor = check(client.get("/api/motor/status").json())
    axis_names = {0: "FEED (mm)", 1: "BEND (°)", 2: "ROTATE (°)", 3: "LIFT (°)"}
    for ax in motor["axes"]:
        print(f"  {axis_names.get(ax['axis'], ax['axis'])}: {ax['position']:.3f}")

    print("\nDone.")
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ortho-Bender SDK basic bend example")
    parser.add_argument("--host", default="http://localhost:8000", help="SDK server base URL")
    args = parser.parse_args()
    main(args.host)
