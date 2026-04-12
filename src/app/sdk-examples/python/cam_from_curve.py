#!/usr/bin/env python3
"""
cam_from_curve.py — 3D wire centerline → B-code → motion execution.

For CAD/CAM developers who have a treatment-plan polyline and want to
drive the wire bender without writing any discretization code.

Pipeline:
  1. Build a sample 3D polyline (replace with your own CAD export)
  2. POST /api/cam/generate to preview the B-code (no motion)
  3. POST /api/cam/execute to generate + dispatch in one shot
  4. Poll /api/bending/status until the sequence finishes

Requirements:
  pip install httpx
"""

from __future__ import annotations

import argparse
import math
import time

import httpx


def check(resp: dict) -> dict:
    if not resp.get("success"):
        raise RuntimeError(f"[{resp.get('code')}] {resp.get('error')}")
    return resp["data"]


def sample_arch_curve(n: int = 12) -> list[dict]:
    """Generate a 40 mm parabolic arch as a stand-in for a CAD export."""
    pts = []
    for i in range(n):
        t = i / (n - 1)
        x = 40.0 * t
        y = 4.0 * (1.0 - (2.0 * t - 1.0) ** 2)  # parabola apex at x=20
        z = 0.5 * math.sin(math.pi * t)
        pts.append({"x": round(x, 3), "y": round(y, 3), "z": round(z, 3)})
    return pts


def main(host: str, execute: bool) -> None:
    client = httpx.Client(base_url=host, timeout=15.0)
    points = sample_arch_curve()
    print(f"=== Input curve: {len(points)} points ===")

    # 1. Preview — no motion
    preview = check(client.post("/api/cam/generate", json={
        "points": points,
        "material": 0,          # SS_304
        "wire_diameter_mm": 0.457,
        "min_segment_mm": 1.0,
        "apply_springback": True,
    }).json())
    print(f"\n=== B-code preview ({preview['segment_count']} segments) ===")
    print(f"  total length : {preview['total_length_mm']:.2f} mm")
    print(f"  max bend     : {preview['max_bend_deg']:.2f}°")
    for i, s in enumerate(preview["steps"]):
        print(f"  [{i}] L={s['L_mm']:6.2f}  β={s['beta_deg']:7.2f}  θ={s['theta_deg']:6.2f}")
    if preview["warnings"]:
        print("  warnings:", preview["warnings"])

    if not execute:
        print("\n(preview only; pass --execute to dispatch motion)")
        return

    # 2. Execute — CAM → motor in one shot
    print("\n=== Executing on hardware ===")
    result = check(client.post("/api/cam/execute", json={
        "points": points,
        "material": 0,
        "wire_diameter_mm": 0.457,
    }).json())
    print(f"  dispatched={result['dispatched']}, steps={result['step_count']}")

    # 3. Poll bending status
    print("\n=== Progress ===")
    while True:
        st = check(client.get("/api/bending/status").json())
        print(f"  step {st['current_step']}/{st['total_steps']}  "
              f"{st['progress_pct']:.0f}%  running={st['running']}")
        if not st["running"]:
            break
        time.sleep(0.2)

    # 4. Final axis positions
    motor = check(client.get("/api/motor/status").json())
    print("\n=== Final axes ===")
    axis_names = {0: "FEED (mm)", 1: "BEND (°)", 2: "ROTATE (°)", 3: "LIFT (°)"}
    for ax in motor["axes"]:
        print(f"  {axis_names[ax['axis']]}: {ax['position']:.3f}")

    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ortho-Bender CAM-from-curve example")
    parser.add_argument("--host", default="http://localhost:8000")
    parser.add_argument("--execute", action="store_true", help="also dispatch motion")
    args = parser.parse_args()
    main(args.host, args.execute)
