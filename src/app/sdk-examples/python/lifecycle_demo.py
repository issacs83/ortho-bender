#!/usr/bin/env python3
"""
lifecycle_demo.py — Camera · Motor connect/disconnect round trip.

Demonstrates the SDK session lifecycle endpoints added for safe maintenance
and long-idle workflows:

  Camera:  POST /api/camera/connect   · /api/camera/disconnect
  Motor :  POST /api/motor/enable     · /api/motor/disable

Scenario:
  1. Print initial camera.power_state and motor.driver_enabled
  2. Disconnect the camera (Vimba X SDK graceful shutdown)
  3. Try to capture → expect CAMERA_OFFLINE, handle gracefully
  4. Reconnect camera, capture succeeds
  5. Disable motor drivers (DRV_ENN released → FREE-WHEEL)
  6. Try to move → expect motor to still accept/reject per state
  7. Re-enable drivers, normal operation restored

Requirements:
  pip install httpx

Usage:
  python lifecycle_demo.py --host http://localhost:8000
"""

from __future__ import annotations

import argparse

import httpx


def envelope(resp: dict) -> tuple[bool, dict | None, str | None, str | None]:
    """Return (success, data, code, error) from an API envelope."""
    return (
        bool(resp.get("success")),
        resp.get("data"),
        resp.get("code"),
        resp.get("error"),
    )


def check(resp: dict) -> dict:
    ok_, data, code, error = envelope(resp)
    if not ok_:
        raise RuntimeError(f"[{code}] {error}")
    assert data is not None
    return data


def main(host: str) -> None:
    client = httpx.Client(base_url=host, timeout=10.0)

    print("=== Initial state ===")
    cam = check(client.get("/api/camera/status").json())
    mot = check(client.get("/api/motor/status").json())
    print(f"  camera.power_state    : {cam['power_state']}")
    print(f"  camera.backend        : {cam['backend']}")
    print(f"  motor.driver_enabled  : {mot['driver_enabled']}")
    print(f"  motor.state           : {mot['state']}")

    # ---- Camera lifecycle ----------------------------------------------
    print("\n=== Camera: disconnect ===")
    cam = check(client.post("/api/camera/disconnect").json())
    print(f"  power_state → {cam['power_state']}  (expect: off)")

    print("\n=== Camera: capture while offline (should fail gracefully) ===")
    r = client.post("/api/camera/capture")
    if r.status_code == 412:
        env = r.json()
        print(f"  412 Precondition Failed: {env.get('code')} — {env.get('error')}")
    else:
        print(f"  unexpected status {r.status_code}: {r.text[:200]}")

    print("\n=== Camera: reconnect ===")
    cam = check(client.post("/api/camera/connect").json())
    print(f"  power_state → {cam['power_state']}  (expect: on)")
    print(f"  backend     → {cam['backend']}")

    # Capture should work again — request JPEG bytes
    r = client.post("/api/camera/capture")
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
        print(f"  capture OK: {len(r.content)} bytes ({r.headers['content-type']})")
    else:
        print(f"  capture failed: {r.status_code} {r.text[:200]}")

    # ---- Motor lifecycle -----------------------------------------------
    # Make sure the motor is IDLE before toggling DRV_ENN.
    client.post("/api/motor/stop")

    print("\n=== Motor: disable drivers (FREE-WHEEL) ===")
    mot = check(client.post("/api/motor/disable").json())
    print(f"  driver_enabled → {mot['driver_enabled']}  (expect: False)")
    print("  Axes are now free-wheeling — manual rotation is possible.")
    print("  ⚠  This is NOT an E-STOP substitute. Use /api/motor/estop for safety.")

    print("\n=== Motor: disable while moving is rejected ===")
    # Kick off a short bending sequence and try to disable mid-motion.
    check(client.post("/api/motor/enable").json())
    check(client.post("/api/bending/execute", json={
        "steps":            [{"L_mm": 10.0, "beta_deg": 0.0, "theta_deg": 30.0}],
        "material":         0,
        "wire_diameter_mm": 0.457,
    }).json())
    env = client.post("/api/motor/disable").json()
    ok_, _, code, error = envelope(env)
    if not ok_ and code == "MOTOR_BUSY":
        print(f"  Correctly refused: [{code}] {error}")
    else:
        print(f"  Unexpected response: success={ok_} code={code}")

    # Wait for the move to finish, then re-enable cleanly.
    import time
    for _ in range(50):
        b = check(client.get("/api/bending/status").json())
        if not b["running"]:
            break
        time.sleep(0.1)

    print("\n=== Motor: re-enable drivers ===")
    mot = check(client.post("/api/motor/enable").json())
    print(f"  driver_enabled → {mot['driver_enabled']}  (expect: True)")

    print("\nDone.")
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ortho-Bender SDK lifecycle demo")
    parser.add_argument("--host", default="http://localhost:8000", help="SDK server base URL")
    args = parser.parse_args()
    main(args.host)
