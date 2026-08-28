#!/usr/bin/env python3
"""Calibrate FEED against a ruler.

FEED has no limit switch and no encoder, so its steps-per-mm cannot be
derived the way BEND's was from its limit disc. It also cannot be
computed from the roller diameter, because nobody has measured the
roller. One physical measurement settles both unknowns at once: feed a
commanded length, measure the wire that actually came out, and the ratio
is the correction.

    python3 calibrate-feed.py --base http://192.168.219.146:8000
    (mark the wire, run the feed, measure, type the number)

Feeding 100 mm and mis-measuring by 1 mm leaves a 1% error. Feed the
longest length your setup allows and measure it carefully -- every later
bend inherits this number.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

FEED = 0


def call(base, path, method="GET", body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://192.168.219.146:8000")
    ap.add_argument("--mm", type=float, default=100.0,
                    help="length to feed for the measurement (default 100)")
    ap.add_argument("--speed", type=float, default=10.0, help="mm/s")
    ap.add_argument("--measured", type=float,
                    help="skip the prompt and use this measured length")
    args = ap.parse_args()

    cal = call(args.base, "/api/motor/calibration")["data"]
    old = float(cal["steps_per_unit"][str(FEED)])
    print(f"current FEED calibration: {old} steps/mm "
          f"({1/old:.4f} mm per step)")

    if args.measured is None:
        print(f"\nMark the wire at the outlet, then press Enter to feed "
              f"{args.mm} mm.")
        input("  ready> ")

    before = next(a for a in call(args.base, "/api/motor/status")["data"]["axes"]
                  if a["axis"] == FEED)["position"]
    call(args.base, "/api/motor/move", "POST",
         {"axis": FEED, "distance": args.mm, "speed": args.speed})
    time.sleep(1.0)
    after = next(a for a in call(args.base, "/api/motor/status")["data"]["axes"]
                 if a["axis"] == FEED)["position"]
    commanded = after - before
    print(f"\ncounter advanced {commanded:.3f} mm "
          f"(what the controller believes it fed)")

    measured = args.measured
    if measured is None:
        while True:
            try:
                measured = float(input("measured wire length in mm> "))
                if measured > 0:
                    break
            except ValueError:
                pass
            print("  enter a positive number")

    new = round(old * (commanded / measured), 4)
    err = (measured - commanded) / commanded * 100.0
    print(f"\ncommanded {commanded:.3f} mm, measured {measured:.3f} mm "
          f"({err:+.1f}%)")
    print(f"corrected calibration: {old} -> {new} steps/mm "
          f"({1/new:.4f} mm per step)")

    if abs(err) < 0.05:
        print("already within 0.05% — leaving it alone")
        return 0

    ans = input("\nwrite this to the board? [y/N] ").strip().lower()
    if ans != "y":
        print("not written")
        return 0

    r = call(args.base, "/api/motor/calibration", "POST",
             {"axis": FEED, "steps_per_unit": new})
    print("written:", json.dumps(r.get("data", {}))[:200])
    print(f"\nspeed ceiling is now {8000/new:.1f} mm/s (8000 Hz / {new})")
    print("Re-run with a fresh mark to confirm it landed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
