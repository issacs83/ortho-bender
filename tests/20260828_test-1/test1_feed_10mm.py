#!/usr/bin/env python3
"""
test1 — 장비 접속 → 피더(FEED) 10 mm 이송 → 완료 대기 → 접속 해지

  # WiFi IP 를 알 때 — 그 주소로 바로 접속
  python3 test1_feed_10mm.py --base http://192.168.0.42:8000 --mm 10

  # WiFi IP 를 모를 때 — 유선으로 붙어 /api/wifi/status 로 IP 를 받아 세션 전환
  python3 test1_feed_10mm.py --wifi --mm 10

  # AP 접속부터 시킬 때
  python3 test1_feed_10mm.py --wifi-ssid lab-wifi --wifi-password '****' --mm 10

주의: FEED(axis 0)는 회전 롤러라 API 단위가 deg 입니다.
      mm 지령은 롤러 원주로 환산해서 보냅니다 (--diameter 로 실측값 지정).
      장비의 FEED 축이 이미 mm 로 캘리브레이션되어 있다면 --feed-unit mm 를 쓰세요.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

import httpx

DEFAULT_BASE = "http://192.168.77.2:8000"      # 유선. WiFi 는 --base 또는 --wifi
AXIS_FEED = 0
POLL_S = 0.2
ARRIVE_TOL_DEG = 0.02          # 도달 판정 여유 (서버 판정은 2 step)


class ObError(RuntimeError):
    """envelope 의 success=false 응답."""

    def __init__(self, code: str | None, message: str | None):
        super().__init__(f"[{code}] {message}")
        self.code = code


def call(c: httpx.Client, method: str, path: str, **kw):
    """모든 REST 응답은 {success, data, error, code} envelope 이다."""
    r = c.request(method, path, **kw)
    r.raise_for_status()                       # 5xx / 422
    body = r.json()
    if not body.get("success"):                # 업무 실패는 HTTP 200 으로 온다
        raise ObError(body.get("code"), body.get("error"))
    return body["data"]


# ---------------------------------------------------------------- 접속 / 해지

def open_session(base_url: str, timeout: float) -> httpx.Client:
    """세션을 열고 장비가 명령을 받을 수 있는 상태인지 확인한다."""
    c = httpx.Client(base_url=base_url, timeout=timeout)

    r = c.get("/health")                       # 프로세스 생존
    r.raise_for_status()
    print(f"[connect] {base_url}  health={r.json()}")

    st = call(c, "GET", "/api/system/status")
    print(f"[connect] state={st['motion_state']} ipc={st['ipc_connected']} "
          f"alarms={st['active_alarms']} uptime={st['uptime_s']:.0f}s")

    if st["motion_state"] in (5, 6):           # 5=FAULT, 6=ESTOP
        c.close()
        raise SystemExit(
            f"장비가 state={st['motion_state']} (FAULT/ESTOP) 입니다. "
            f"원인을 해소한 뒤 POST /api/motor/reset 을 먼저 실행하세요."
        )
    return c


def enable_driver(c: httpx.Client) -> None:
    call(c, "POST", "/api/motor/enable")       # DRV_ENN active — idempotent
    print("[connect] driver enabled")


# ---------------------------------------------------------------- WiFi

def _pick(d: dict, *keys, default=None):
    """응답 키 이름이 펌웨어 버전마다 조금씩 달라서 후보를 순서대로 찾는다."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def wifi_status(c: httpx.Client) -> dict:
    """현재 AP 연결 정보 — SSID / RSSI / IP."""
    w = call(c, "GET", "/api/wifi/status")
    return {
        "ssid": _pick(w, "ssid", "SSID"),
        "rssi": _pick(w, "rssi", "RSSI", "signal"),
        "ip":   _pick(w, "ip", "ip_address", "address", "ipv4"),
        "raw":  w,
    }


def wifi_join(c: httpx.Client, ssid: str, password: str) -> dict:
    """AP 에 접속한다. 성공 시 응답에 새 IP 가 포함된다."""
    print(f"[wifi] connecting to SSID {ssid!r} …")
    r = call(c, "POST", "/api/wifi/connect",
             json={"ssid": ssid, "password": password})
    ip = _pick(r, "ip", "ip_address", "address", "ipv4")
    print(f"[wifi] connected. ip={ip}")
    return r


def retarget_to_wifi(c: httpx.Client, port: int, timeout: float) -> httpx.Client:
    """장비의 WiFi IP 를 조회해서, 필요하면 그 주소로 세션을 다시 연다."""
    w = wifi_status(c)
    if not w["ip"]:
        c.close()
        raise SystemExit(
            "장비가 WiFi 에 연결되어 있지 않습니다 (/api/wifi/status 에 IP 없음). "
            "--wifi-ssid / --wifi-password 로 접속시키거나, "
            "--base 에 WiFi IP 를 직접 지정하세요.\n"
            f"  응답: {w['raw']}"
        )

    rssi = f" rssi={w['rssi']}" if w["rssi"] is not None else ""
    print(f"[wifi] ssid={w['ssid']!r}{rssi} ip={w['ip']}")

    wifi_base = f"http://{w['ip']}:{port}"
    if httpx.URL(wifi_base).host == c.base_url.host:
        print("[wifi] 이미 WiFi 주소로 접속되어 있습니다")
        return c

    print(f"[wifi] 세션 전환: {c.base_url} → {wifi_base}")
    c.close()
    return open_session(wifi_base, timeout)


def disconnect(c: httpx.Client) -> None:
    """코일을 해제하고 세션을 닫는다. 어떤 경우에도 예외를 밖으로 던지지 않는다."""
    try:
        call(c, "POST", "/api/motor/disable")  # IDLE/FAULT/ESTOP 에서만 허용
        print("[disconnect] driver disabled (free-wheel)")
    except ObError as e:
        # 모션 중이면 MOTOR_BUSY — 세션만 정리하고 넘어간다
        print(f"[disconnect] disable 건너뜀: {e}", file=sys.stderr)
    except Exception as e:                     # noqa: BLE001 - 정리 경로
        print(f"[disconnect] disable 실패: {e}", file=sys.stderr)
    finally:
        c.close()
        print("[disconnect] session closed")


# ---------------------------------------------------------------- 이송

def mm_to_deg(mm: float, roller_diameter_mm: float) -> float:
    """롤러 원주 기준 이송 mm → 롤러 회전 deg."""
    return mm / (math.pi * roller_diameter_mm) * 360.0


def wait_idle(c: httpx.Client, timeout_s: float) -> dict:
    """state 가 IDLE 로 돌아오고 대기열이 빌 때까지 기다린다."""
    deadline = time.monotonic() + timeout_s
    while True:
        st = call(c, "GET", "/api/motor/status")
        queued = call(c, "GET", "/api/motor/limits").get("queued", 0)
        if st["state"] == 0 and queued == 0:
            return st
        if st["state"] in (5, 6):
            raise RuntimeError(f"이송 중 state={st['state']} (FAULT/ESTOP) 발생")
        if time.monotonic() > deadline:
            raise TimeoutError(f"이송 완료 대기 시간 초과 ({timeout_s}s)")
        time.sleep(POLL_S)


def feed(c: httpx.Client, delta_deg: float, speed: float, timeout_s: float) -> None:
    """현재 위치 기준 delta_deg 만큼 절대 이동(move_to)으로 이송한다."""
    calib = call(c, "GET", "/api/motor/calibration")
    limit = calib["speed_limit"][str(AXIS_FEED)]
    if speed > limit:
        print(f"[feed] speed {speed} → {limit} deg/s 로 클램프 "
              f"(speed_limit = 8kHz / {calib['steps_per_unit'][str(AXIS_FEED)]})")
        speed = limit

    axes = {a["axis"]: a for a in call(c, "GET", "/api/motor/status")["axes"]}
    start = axes[AXIS_FEED]["position"]
    target = start + delta_deg
    print(f"[feed] {start:.3f} → {target:.3f} deg  (Δ{delta_deg:+.3f} @ {speed} deg/s)")

    # 상대 이동(/move)은 1회 상한(FEED 360deg / 10s)에서 조용히 잘린다.
    # 절대 이동(/move_to)은 목표에 닿을 때까지 자동 분할되므로 이쪽을 쓴다.
    # 이 요청은 자기 차례가 끝날 때 응답한다.
    call(c, "POST", "/api/motor/move_to",
         json={"axis": AXIS_FEED, "position": target, "speed": speed})

    st = wait_idle(c, timeout_s)
    axes = {a["axis"]: a for a in st["axes"]}
    final = axes[AXIS_FEED]["position"]
    err = final - target
    print(f"[feed] 완료: {final:.3f} deg (오차 {err:+.3f} deg)")
    if abs(err) > max(ARRIVE_TOL_DEG, abs(delta_deg) * 0.001):
        print(f"[feed] ⚠ 목표에 도달하지 못했습니다 — 축이 막혔는지 확인하세요",
              file=sys.stderr)


# ---------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(
        description="FEED 축 이송 테스트 (WiFi 접속)",
        epilog="WiFi IP 를 알면 --base 로 바로 지정하고, 모르면 --wifi 로 장비에서 조회합니다.",
    )
    p.add_argument("--base", default=os.environ.get("OB_BASE", DEFAULT_BASE),
                   help=f"장비 base URL (env OB_BASE, 기본 {DEFAULT_BASE})")
    p.add_argument("--wifi", action="store_true",
                   help="/api/wifi/status 로 WiFi IP 를 조회해 그 주소로 세션을 전환")
    p.add_argument("--wifi-ssid", help="접속할 AP SSID (지정 시 /api/wifi/connect 실행)")
    p.add_argument("--wifi-password", default="", help="AP 비밀번호")
    p.add_argument("--port", type=int, default=8000, help="WiFi 전환 시 사용할 포트")
    p.add_argument("--mm", type=float, default=10.0, help="이송량 (mm, 음수 = 역방향)")
    p.add_argument("--speed", type=float, default=20.0, help="이송 속도 (deg/s)")
    p.add_argument("--diameter", type=float, default=20.0,
                   help="피드 롤러 직경 (mm) — 실측값으로 바꿔야 mm 이송이 정확합니다")
    p.add_argument("--feed-unit", choices=("deg", "mm"), default="deg",
                   help="FEED 축의 API 단위. 기본 deg (mm 로 캘리브레이션했다면 mm)")
    p.add_argument("--timeout", type=float, default=60.0, help="완료 대기 상한 (s)")
    args = p.parse_args()

    if args.feed_unit == "mm":
        delta = args.mm
        print(f"[plan] FEED {args.mm:+.3f} mm (축 단위 = mm)")
    else:
        delta = mm_to_deg(args.mm, args.diameter)
        print(f"[plan] FEED {args.mm:+.3f} mm → {delta:+.3f} deg "
              f"(롤러 Ø{args.diameter} mm, 원주 {math.pi * args.diameter:.2f} mm)")

    timeout = args.timeout + 10
    try:
        c = open_session(args.base, timeout)
        if args.wifi_ssid:                     # AP 접속부터 시킬 때
            wifi_join(c, args.wifi_ssid, args.wifi_password)
        if args.wifi or args.wifi_ssid:        # WiFi IP 로 세션 전환
            c = retarget_to_wifi(c, args.port, timeout)
        enable_driver(c)
    except httpx.HTTPError as e:
        print(f"[error] 장비에 접속할 수 없습니다 ({args.base}): {e}", file=sys.stderr)
        return 2
    except ObError as e:
        print(f"[error] 접속 확인 실패: {e}", file=sys.stderr)
        return 2

    try:
        feed(c, delta, args.speed, args.timeout)
    except KeyboardInterrupt:
        print("\n[abort] 사용자 중단 — 감속 정지", file=sys.stderr)
        try:
            call(c, "POST", "/api/motor/stop")
            wait_idle(c, 10)
        except Exception:                      # noqa: BLE001 - 정리 경로
            pass
        return 130
    except Exception as e:                     # noqa: BLE001 - 최상위 리포트
        print(f"[error] {e}", file=sys.stderr)
        try:
            call(c, "POST", "/api/motor/stop")
            wait_idle(c, 10)
        except Exception:                      # noqa: BLE001
            pass
        return 1
    finally:
        disconnect(c)                          # 성공/실패 무관하게 항상 해지
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
