"""Measure what the API actually delivers, so the 1 ms question gets
numbers instead of opinions.

Three layers are timed separately, because they fail for different
reasons and only one of them is fixable in software:

  1. HTTP floor      -- /health, no hardware touched
  2. Status read     -- /api/motor/status, no motion
  3. Motion command  -- the smallest possible move

Run on the board (loopback, removes the network) and from the PC (adds
it) and compare: the gap is the network, everything else is us.
"""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 60


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        ok = True
    except Exception:
        ok = False
    return (time.perf_counter() - t0) * 1000.0, ok


def report(name, samples, target_ms=None):
    if not samples:
        print(f"  {name:22s} no samples")
        return
    s = sorted(samples)
    n = len(s)
    p50 = s[n // 2]
    p95 = s[int(n * 0.95)] if n > 20 else s[-1]
    jitter = max(s) - min(s)
    print(f"  {name:22s} n={n:3d}  min={min(s):7.2f}  p50={p50:7.2f}  "
          f"p95={p95:7.2f}  max={max(s):8.2f}  jitter={jitter:8.2f}  (ms)")
    if target_ms:
        over = sum(1 for x in s if x > target_ms)
        print(f"  {'':22s} over {target_ms} ms: {over}/{n} "
              f"({100*over/n:.0f}%)")


print(f"target: {BASE}   samples: {N}\n")

print("=== 1. HTTP floor (no hardware touched) ===")
health = [call("/health")[0] for _ in range(N)]
report("GET /health", health, 1.0)

print("\n=== 2. status read (SPI cached, no motion) ===")
status = [call("/api/motor/status")[0] for _ in range(N)]
report("GET /api/motor/status", status, 1.0)

print("\n=== 3. protection read (service layer) ===")
prot = [call("/api/motor/protection")[0] for _ in range(N)]
report("GET /api/motor/protection", prot, 1.0)

print("\n=== 4. smallest possible motion command ===")
print("    BEND +0.5 deg, alternating direction so it stays put")
moves, sign = [], 1
for i in range(min(N, 20)):
    ms, ok = call("/api/motor/move", "POST",
                  {"axis": 1, "distance": 0.5 * sign, "speed": 60.0})
    if ok:
        moves.append(ms)
    sign = -sign
    time.sleep(0.05)
report("POST /api/motor/move", moves, 1.0)

print("\n=== verdict ===")
if moves:
    print(f"  A 1 ms control period needs a full command round trip inside")
    print(f"  1 ms. The median motion command takes "
          f"{sorted(moves)[len(moves)//2]:.1f} ms.")
    print(f"  That is {sorted(moves)[len(moves)//2]:.0f}x the budget, and the")
    print(f"  spread ({max(moves)-min(moves):.0f} ms) is what breaks")
    print(f"  periodicity even when the mean looks acceptable.")
