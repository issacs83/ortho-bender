#!/usr/bin/env python3
"""precise_positioning.py — 축 직접 제어 예제 (CAD/CAM 개발자용).

원점 확보(홈) → 절대 좌표 이동 → 도달 검증까지의 최소 시퀀스를 보여줍니다.
교정·티칭·지그 정렬처럼 B-code를 거치지 않고 축을 직접 다룰 때 쓰는 패턴입니다.

축 규약(반드시 숙지): docs/sdk/06_AXIS_CONVENTIONS.md
  axis 0 FEED  : 회전, deg, + = 시계방향, 센서 없음
  axis 1 BEND  : 회전, deg, + = 시계방향, 리밋 센서 있음
  axis 3 LIFT  : 직선, mm,  + = 아래,     최상단 센서 = 0

Usage:
    python3 precise_positioning.py [--host 192.168.77.2] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import time

import requests

FEED, BEND, ROTATE, LIFT = 0, 1, 2, 3
AXIS_NAME = {FEED: "FEED", BEND: "BEND", ROTATE: "ROTATE", LIFT: "LIFT"}
AXIS_UNIT = {FEED: "deg", BEND: "deg", ROTATE: "deg", LIFT: "mm"}
STATE_NAME = {0: "IDLE", 1: "HOMING", 2: "RUNNING", 3: "JOGGING",
              4: "STOPPING", 5: "FAULT", 6: "ESTOP"}


class Bender:
    """Thin REST client — every call raises on the envelope's error."""

    def __init__(self, host: str, timeout: float = 180.0) -> None:
        self.base = f"http://{host}:8000"
        self.timeout = timeout

    def _call(self, method: str, path: str, **kw):
        r = requests.request(method, self.base + path, timeout=self.timeout, **kw)
        r.raise_for_status()
        env = r.json()
        if not env.get("success"):
            raise RuntimeError(f'{env.get("code")}: {env.get("error")}')
        return env["data"]

    # -- queries ----------------------------------------------------------
    def status(self):
        return self._call("GET", "/api/motor/status")

    def limits(self):
        return self._call("GET", "/api/motor/limits")

    def calibration(self):
        return self._call("GET", "/api/motor/calibration")

    def position(self, axis: int) -> float:
        for a in self.status()["axes"]:
            if a["axis"] == axis:
                return a["position"]
        raise KeyError(f"axis {axis} not present on this machine")

    # -- motion -----------------------------------------------------------
    def home(self, axis_mask: int = 0, timeout_s: float = 120.0):
        """Home the switch-equipped axes and WAIT for completion."""
        self._call("POST", "/api/motor/home", json={"axis_mask": axis_mask})
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            time.sleep(0.3)
            lim = self.limits()
            if not lim["homing"]:
                if lim["error"]:
                    raise RuntimeError(f"homing failed: {lim['error']}")
                return lim
        raise TimeoutError("homing did not finish in time")

    def move_to(self, axis: int, position: float, speed: float):
        """Absolute move. Ramps finish INSIDE the target, long moves are
        split automatically by the server."""
        return self._call("POST", "/api/motor/move_to",
                          json={"axis": axis, "position": position, "speed": speed})

    def stop(self):
        return self._call("POST", "/api/motor/stop")

    def estop_active(self) -> bool:
        return self.status()["state"] == 6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.77.2")
    ap.add_argument("--dry-run", action="store_true",
                    help="query only, do not move the machine")
    args = ap.parse_args()

    bot = Bender(args.host)

    # 1) 상태 점검 — E-STOP 이면 아무 것도 하지 않는다
    st = bot.status()
    print(f"state = {STATE_NAME.get(st['state'], st['state'])}")
    if bot.estop_active():
        print("E-STOP 상태입니다. 해제(POST /api/motor/reset) 후 다시 실행하세요.")
        return 1

    cal = bot.calibration()["steps_per_unit"]
    for ax in (FEED, BEND, LIFT):
        print(f"  {AXIS_NAME[ax]:5s} {bot.position(ax):9.3f} {AXIS_UNIT[ax]:3s}"
              f"  ({cal[str(ax)]} steps/{AXIS_UNIT[ax]})")

    if args.dry_run:
        return 0

    # 2) 원점 확보 — 센서가 있는 축(BEND, LIFT)만 대상
    print("\n홈 시퀀스 (BEND + LIFT)...")
    lim = bot.home(axis_mask=0)
    print(f"  완료. homed={lim['homed']}  switches={lim['limits']}")

    # 3) 절대 좌표 이동. 단위는 축을 따른다 (BEND=deg, LIFT=mm, LIFT의 +는 아래)
    targets = [
        (BEND, 45.0, 120.0),      # 45 deg 로 @120 deg/s
        (LIFT, 50.0, 20.0),       # 최상단에서 50 mm 아래로 @20 mm/s
        (BEND, 0.0, 120.0),       # 원점 복귀
        (LIFT, 0.0, 20.0),
    ]
    print("\n절대 이동:")
    for axis, target, speed in targets:
        bot.move_to(axis, target, speed)
        landed = bot.position(axis)
        unit = AXIS_UNIT[axis]
        print(f"  {AXIS_NAME[axis]:5s} → {target:8.2f} {unit}"
              f"   도달 {landed:8.2f} {unit}   오차 {landed - target:+.3f} {unit}")

    print("\n완료.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n중단됨 — 장비를 멈춥니다.")
        try:
            Bender(sys.argv[-1] if "--host" in sys.argv else "192.168.77.2").stop()
        except Exception:
            pass
        sys.exit(130)
