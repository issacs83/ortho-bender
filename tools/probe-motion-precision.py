"""Is the 0.1 mm overshoot a fixed step count or a fixed time?

    python3 tools/probe-motion-precision.py <board-ip>

Moves LIFT in small increments -- make sure the carriage has room.

If PWM keeps pulsing for a fixed interval after the accounting says
"done", the excess scales with the frequency the axis was running at --
so a faster commanded move overshoots by more steps, not fewer. A fixed
step bias would stay constant instead. The two have completely different
fixes, so measure before touching anything.
"""
import json
import time
import urllib.request

import sys

_arg = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
BASE = _arg if _arg.startswith("http") else f"http://{_arg}:8000"
LIFT = 3
SPU = 200.0          # steps per mm


def call(path, method="GET", body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def pos():
    d = call("/api/motor/status")
    return next(a for a in d["data"]["axes"] if a["axis"] == LIFT)["position"]


def trial(dist_mm, speed):
    p0 = pos()
    call("/api/motor/move", "POST",
         {"axis": LIFT, "distance": dist_mm, "speed": speed})
    time.sleep(0.4)
    moved = pos() - p0
    err_mm = moved - dist_mm
    return moved, err_mm, round(err_mm * SPU)


print("=== does the excess scale with speed? (distance fixed at 0.1 mm) ===")
print(f"{'speed mm/s':>11} {'moved mm':>10} {'err mm':>9} {'err steps':>10}")
sign = 1
for speed in (1.0, 2.0, 5.0, 10.0, 20.0):
    moved, err, steps = trial(0.1 * sign, speed)
    print(f"{speed:>11.1f} {moved:>10.4f} {err*sign:>9.4f} {steps*sign:>10d}")
    sign = -sign
    time.sleep(0.3)

print("\n=== does the excess scale with distance? (speed fixed at 5 mm/s) ===")
print(f"{'dist mm':>9} {'moved mm':>10} {'err mm':>9} {'err steps':>10} {'err %':>8}")
sign = 1
for dist in (0.05, 0.1, 0.2, 0.5, 1.0, 5.0):
    moved, err, steps = trial(dist * sign, 5.0)
    pct = 100 * err / dist if dist else 0
    print(f"{dist:>9.2f} {moved:>10.4f} {err*sign:>9.4f} {steps*sign:>10d} "
          f"{pct*sign:>7.1f}%")
    sign = -sign
    time.sleep(0.3)

print("\n=== what does the profile say? ===")
prof = call("/api/motor/profiles")["data"]["profiles"][str(LIFT)]
print(f"  LIFT profile: {prof}")
print("  start_hz is the floor the PWM runs at; at 200 Hz one pulse is 5 ms,")
print("  so every 5 ms of shutdown latency costs one step (0.005 mm).")
