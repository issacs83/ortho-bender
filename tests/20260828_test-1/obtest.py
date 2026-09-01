#!/usr/bin/env python3
"""
obtest.py — Ortho-Bender SDK 전체 API 테스트 콘솔

  WiFi 로 자동 접속하고, 경로 앞부분(/api/...) 없이 명령 이름만 입력하면 실행합니다.
  종료 시 세션은 자동으로 정리됩니다.

사용법
  python3 obtest.py                      # 대화형 콘솔 (WiFi 자동 접속·자동 탐색)
  python3 obtest.py --host 192.168.0.42  # WiFi IP 를 알 때
  python3 obtest.py --scan               # WiFi 대역을 스캔해서 장비 찾기
  python3 obtest.py motor.status         # 한 번만 실행하고 종료
  python3 obtest.py feed 5               # 피더 5 mm 이송

콘솔 안에서
  ls [패턴]          지원하는 명령 목록
  help <명령>        인자 설명
  <명령> k=v k=v     API 실행        예) move_to axis=1 position=45 speed=8
  <명령> v v         위치 인자도 가능  예) reg.read tmc260c_0 0x04
  feed.cal 60        FEED 를 60 deg 돌린 뒤 실제 배출 길이를 입력 → mm/deg 계수 실측·저장
  feed 5             피더 5 mm 이송 (실측 계수로 deg 환산 후 move_to)
  feed 10 mmps=10    초당 10 mm 로 10 mm 이송 (= 1 cm/s)
  feed 10 trace=true 이동 중 위치를 샘플링해 오버슈트·역회전 진단
  feed.step 0.01 count=20   0.01 mm 씩 20회 (절대 그리드, 분해능 검사 포함)
  feed.step 0.1 snap=true   0.1 mm 에 가장 가까운 정수 스텝으로 스냅 — 매회 완전 등간격
  mstep              마이크로스텝(DRVCTRL.MRES) 조회 · mstep 64 로 변경
  ws motor 5         WebSocket 5초 구독
  raw GET /api/...   등록되지 않은 경로 직접 호출
  discover           현재 네트워크에서 장비 찾기
  reconnect / base <url> / quit

인자 값은 JSON 으로 해석됩니다 (true, 12, 1.5, [1,2], {"a":1}).
따옴표 없는 문자열은 그대로 문자열입니다 (mono8, tmc260c_0, 0x04).
@파일.json 은 파일 내용을 값으로 읽습니다 (예: points=@curve.json).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
import traceback
from dataclasses import dataclass

import httpx

DEFAULT_WIRED = "http://192.168.77.2:8000"
DEFAULT_PORT = 8000

# FEED 축은 단위가 deg 라서 "축 1도당 배출되는 와이어 mm" 가 있어야 mm 이송이 된다.
# 이 값은 기계마다 다르므로 추측하지 말고 feed.cal 로 실측해서 저장한다.
FEED_CAL_FILE = os.path.join(os.path.expanduser("~"), ".obtest_feed.json")
ROLLER_MM = 20.0            # --roller 로만 쓰이는 보조 입력 (직경 → mm/deg 환산)
MM_PER_DEG = None           # 실측/지정된 계수. None 이면 미교정 상태

# ───────────────────────────────────────────────────────────── 콘솔 출력

class C:
    """터미널 색상 (파이프로 넘길 때는 자동 비활성)."""
    on = sys.stdout.isatty()
    @classmethod
    def _w(cls, code, s): return f"\033[{code}m{s}\033[0m" if cls.on else s
    @classmethod
    def dim(cls, s):  return cls._w("2", s)
    @classmethod
    def red(cls, s):  return cls._w("31;1", s)
    @classmethod
    def grn(cls, s):  return cls._w("32", s)
    @classmethod
    def yel(cls, s):  return cls._w("33", s)
    @classmethod
    def blu(cls, s):  return cls._w("36", s)
    @classmethod
    def bold(cls, s): return cls._w("1", s)


VERBOSE = False


def info(msg):  print(C.blu("· ") + msg)
def ok(msg):    print(C.grn("✓ ") + msg)


def _err(text):
    """stdout 과 순서가 뒤섞이지 않도록 flush 후 stderr 로."""
    sys.stdout.flush()
    print(text, file=sys.stderr, flush=True)


def warn(msg):
    _err(C.yel("⚠ ") + msg)


def fail(msg, exc: BaseException | None = None):
    """에러는 무엇이든 콘솔에 남긴다."""
    _err(C.red("✗ ") + msg)
    if exc is not None:
        _err(C.red(f"  {type(exc).__name__}: {exc}"))
        if VERBOSE:
            traceback.print_exc()


def dump(obj, limit=4000):
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(s) > limit:
        s = s[:limit] + C.dim(f"\n… ({len(s) - limit} chars 생략, --verbose 로 전체 출력)")
    print(s)


# ───────────────────────────────────────────────────────────── 명령 레지스트리

@dataclass
class Cmd:
    name: str
    method: str
    path: str
    params: tuple = ()          # 위치 인자 순서 / help 표시용
    kind: str = "json"          # json | binary | stream | ws
    note: str = ""
    query: bool = False         # POST 인데 body 가 아니라 query 로 보내는 경우
    alias: tuple = ()

    @property
    def path_params(self):
        return [p[1:-1] for p in self.path.split("/") if p.startswith("{")]


CMDS: list[Cmd] = [
    # ── system ───────────────────────────────────────────────
    Cmd("health",          "GET",  "/health", note="프로세스 생존 확인 (envelope 아님)"),
    Cmd("system.status",   "GET",  "/api/system/status", note="전체 헬스 리포트", alias=("sys",)),
    Cmd("system.version",  "GET",  "/api/system/version", note="SDK / M7 펌웨어 버전"),
    Cmd("system.psu",      "GET",  "/api/system/psu", note="PSU 프리셋 목록·현재값"),
    Cmd("system.psu.set",  "POST", "/api/system/psu", ("psu_id",), note="PSU 프리셋 선택"),
    Cmd("system.reboot",   "POST", "/api/system/reboot", ("confirm",), note="재부팅 (confirm=true 필수)"),

    # ── motor: 상태 ──────────────────────────────────────────
    Cmd("motor.status",    "GET",  "/api/motor/status", note="축 위치·속도·신호", alias=("ms",)),
    Cmd("limits",          "GET",  "/api/motor/limits", note="리밋·홈잉·대기열(queued)"),

    # ── motor: 이동 ──────────────────────────────────────────
    Cmd("move_to",         "POST", "/api/motor/move_to", ("axis", "position", "speed"),
        note="절대 이동 (자동 분할, 완료 시 응답)"),
    Cmd("move",            "POST", "/api/motor/move", ("axis", "distance", "speed"),
        note="상대 이동 (1회 상한 초과분은 잘림)"),
    Cmd("jog",             "POST", "/api/motor/jog", ("axis", "direction", "speed", "distance"),
        note="조그 (distance=0 → 연속)"),
    Cmd("jog.start",       "POST", "/api/motor/jog/start",
        ("axis", "direction", "speed", "distance", "continuous"),
        note="누르고 있는 동안 회전 (폴백 5s / continuous=true 60s)"),
    Cmd("jog.stop",        "POST", "/api/motor/jog/stop", ("axis",), note="조그 정지 · 홈잉 취소"),

    # ── motor: 원점 ──────────────────────────────────────────
    Cmd("home",            "POST", "/api/motor/home", ("axis_mask",),
        note="리밋 호밍 (0=전체, 0x02=BEND, 0x08=LIFT). 즉시 반환"),
    Cmd("zero",            "POST", "/api/motor/zero", ("axis", "value"),
        note="현재 위치를 원점으로 선언 (모션 없음)"),

    # ── motor: 설정 ──────────────────────────────────────────
    Cmd("profiles",        "GET",  "/api/motor/profiles", note="축별 모션 프로파일"),
    Cmd("profiles.set",    "PUT",  "/api/motor/profiles/{axis}", ("axis",),
        note="부분 업데이트: jog_speed/max_speed/step_size/start_hz/accel/decel/shape"),
    Cmd("protection",      "GET",  "/api/motor/protection", note="리밋 자동정지·축별 토크"),
    Cmd("protection.set",  "PUT",  "/api/motor/protection", (),
        note='예) protection.set axes={"1":{"run_cs":14}}'),
    Cmd("calibration",     "GET",  "/api/motor/calibration",
        note="steps_per_unit / distance_limit / speed_limit", alias=("calib",)),
    Cmd("calibration.set", "POST", "/api/motor/calibration", ("axis", "steps_per_unit")),
    Cmd("stallguard",      "GET",  "/api/motor/stallguard", note="SG 임계·측정값", alias=("sg",)),
    Cmd("stallguard.set",  "PUT",  "/api/motor/stallguard", ("axis", "sgt", "filter"),
        note="sgt −64~63 (낮을수록 민감)"),

    # ── motor: 정지·전원 ─────────────────────────────────────
    Cmd("stop",            "POST", "/api/motor/stop", note="전 축 감속 정지"),
    Cmd("estop",           "POST", "/api/motor/estop", note="🚨 비상 정지 (대기열까지 폐기)"),
    Cmd("reset",           "POST", "/api/motor/reset", ("axis_mask",), note="E-STOP·폴트 래치 해제"),
    Cmd("enable",          "POST", "/api/motor/enable", note="코일 여자 (DRV_ENN active)"),
    Cmd("disable",         "POST", "/api/motor/disable", note="코일 해제 (FREE-WHEEL, 모션 중 거부)"),

    # ── motor: 진단 ──────────────────────────────────────────
    Cmd("diag.backend",    "GET",  "/api/motor/diag/backend", note="mock | spidev | m7"),
    Cmd("diag.probe",      "GET",  "/api/motor/diag/probe", note="드라이버 SPI 응답 확인"),
    Cmd("diag.spi",        "GET",  "/api/motor/diag/spi-test", note="SPI 왕복 지연"),
    Cmd("diag.dump",       "GET",  "/api/motor/diag/dump/{driver}", ("driver",),
        note="tmc260c_0 | tmc260c_1 | tmc5072"),
    Cmd("reg.read",        "GET",  "/api/motor/diag/register/{driver}/{addr}", ("driver", "addr")),
    Cmd("reg.write",       "POST", "/api/motor/diag/register/{driver}/{addr}",
        ("driver", "addr", "value"), note="안전 가드: CS≤19, TOFF 1–8"),

    # ── camera ───────────────────────────────────────────────
    Cmd("camera.status",   "GET",  "/api/camera/status", note="연결·해상도·노출·power_state", alias=("cs",)),
    Cmd("capture",         "POST", "/api/camera/capture", ("quality",), kind="binary", query=True,
        note="단일 JPEG 저장 (out=파일명 지정 가능)"),
    Cmd("stream",          "GET",  "/api/camera/stream", ("fps",), kind="stream", query=True,
        note="MJPEG 을 seconds 초 동안 수신하며 프레임 수 측정"),
    Cmd("camera.settings", "POST", "/api/camera/settings", ("exposure_us", "gain_db", "format"),
        note="노출 18.9µs~10s / 게인 0~48dB / mono8·mono12·rgb8"),
    Cmd("controls",        "GET",  "/api/camera/controls", note="드라이버 전체 컨트롤 열거"),
    Cmd("controls.set",    "POST", "/api/camera/controls", ("id", "value"),
        note="value 는 int 또는 배열 (원시 단위)"),
    Cmd("roi",             "GET",  "/api/camera/roi", note="crop/bounds/default/capture"),
    Cmd("roi.set",         "POST", "/api/camera/roi", ("left", "top", "width", "height"),
        note="드라이버 정렬 보정값이 응답에 담김"),
    Cmd("presets",         "GET",  "/api/camera/presets"),
    Cmd("presets.save",    "POST", "/api/camera/presets", ("name",), note="현재 설정을 저장"),
    Cmd("presets.apply",   "POST", "/api/camera/presets/{name}/apply", ("name",),
        note="응답의 errors 확인 필수"),
    Cmd("presets.delete",  "DELETE", "/api/camera/presets/{name}", ("name",)),
    Cmd("framerate",       "GET",  "/api/camera/framerate"),
    Cmd("framerate.set",   "POST", "/api/camera/framerate", ("fps",), note="낮출수록 노출 상한 ↑"),
    Cmd("camera.connect",  "POST", "/api/camera/connect", note="세션 재오픈 (idempotent)"),
    Cmd("camera.disconnect", "POST", "/api/camera/disconnect", note="이후 CAMERA_OFFLINE"),

    # ── bending ──────────────────────────────────────────────
    Cmd("bending.execute", "POST", "/api/bending/execute", ("steps", "material", "wire_diameter_mm"),
        note='steps=[{"L_mm":10,"beta_deg":0,"theta_deg":30}] (1~128)'),
    Cmd("bending.status",  "GET",  "/api/bending/status", note="running/current_step/progress_pct", alias=("bs",)),
    Cmd("bending.stop",    "POST", "/api/bending/stop"),

    # ── cam ──────────────────────────────────────────────────
    Cmd("cam.generate",    "POST", "/api/cam/generate",
        ("points", "material", "wire_diameter_mm", "min_segment_mm", "apply_springback"),
        note="프리뷰 (모션 없음). points=@curve.json 가능"),
    Cmd("cam.execute",     "POST", "/api/cam/execute",
        ("points", "material", "wire_diameter_mm", "min_segment_mm", "apply_springback"),
        note="⚠ 생성 즉시 모터 디스패치"),

    # ── wifi ─────────────────────────────────────────────────
    Cmd("wifi.status",     "GET",  "/api/wifi/status", note="SSID / RSSI / IP"),
    Cmd("wifi.scan",       "GET",  "/api/wifi/scan"),
    Cmd("wifi.saved",      "GET",  "/api/wifi/saved"),
    Cmd("wifi.connect",    "POST", "/api/wifi/connect", ("ssid", "password"),
        note="⚠ 성공 시 IP 가 바뀌어 현재 세션이 끊길 수 있음"),
    Cmd("wifi.forget",     "POST", "/api/wifi/forget", ("ssid",)),
    Cmd("wifi.disconnect", "POST", "/api/wifi/disconnect"),

    # ── docs ─────────────────────────────────────────────────
    Cmd("docs.tree",       "GET",  "/api/docs/tree", note="장비 탑재 문서 목록"),
    Cmd("docs.file",       "GET",  "/api/docs/file/{path}", ("path",),
        note="예) docs.file sdk/06_AXIS_CONVENTIONS.md"),
    Cmd("docs.download",   "GET",  "/api/docs/download/{path}", ("path",), kind="binary"),

    # ── websocket ────────────────────────────────────────────
    Cmd("ws.motor",        "WS",   "/ws/motor", ("seconds",), kind="ws", note="10 Hz"),
    Cmd("ws.camera",       "WS",   "/ws/camera", ("seconds",), kind="ws", note="~15 fps (max_size 8MB)"),
    Cmd("ws.system",       "WS",   "/ws/system", ("seconds",), kind="ws", note="알람·상태 전이"),
    Cmd("ws.diag",         "WS",   "/ws/motor/diag", ("seconds",), kind="ws", note="200 Hz"),
]

BY_NAME: dict[str, Cmd] = {}
for _c in CMDS:
    BY_NAME[_c.name] = _c
    for _a in _c.alias:
        BY_NAME[_a] = _c


def resolve(token: str) -> Cmd | None:
    """이름 · 별칭 · 마지막 마디 · 부분일치 순으로 명령을 찾는다."""
    t = token.strip().lower().lstrip("/")
    if t in BY_NAME:
        return BY_NAME[t]
    t = t.replace("/", ".")
    if t in BY_NAME:
        return BY_NAME[t]
    tail = [c for c in CMDS if c.name.rsplit(".", 1)[-1] == t]
    if len(tail) == 1:
        return tail[0]
    part = [c for c in CMDS if t in c.name]
    if len(part) == 1:
        return part[0]
    if len(part) > 1:
        fail(f"'{token}' 이 모호합니다 → {', '.join(c.name for c in part[:12])}")
        return None
    if tail:
        fail(f"'{token}' 이 모호합니다 → {', '.join(c.name for c in tail)}")
        return None
    fail(f"알 수 없는 명령: '{token}'  (ls 로 목록 확인)")
    return None


# ───────────────────────────────────────────────────────────── 인자 파싱

def parse_value(tok: str):
    if tok.startswith("@"):
        path = tok[1:]
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    try:
        return json.loads(tok)          # 12, 1.5, true, [..], {..}, "문자열"
    except json.JSONDecodeError:
        return tok                      # mono8, tmc260c_0, 0x04 …


def parse_args(cmd: Cmd, tokens: list[str]) -> dict:
    """k=v 와 위치 인자를 함께 받는다."""
    kv, positional = {}, []
    for t in tokens:
        if "=" in t and not t.startswith("{") and not t.startswith("["):
            k, _, v = t.partition("=")
            kv[k.strip()] = parse_value(v)
        else:
            positional.append(parse_value(t))
    if positional:
        order = [p for p in cmd.path_params] + \
                [p for p in cmd.params if p not in cmd.path_params]
        for name, val in zip(order, positional):
            kv.setdefault(name, val)
        if len(positional) > len(order):
            warn(f"위치 인자 {len(positional) - len(order)}개가 남아 무시됩니다")
    return kv


# ───────────────────────────────────────────────────────────── 세션

class Session:
    def __init__(self, base: str, timeout: float):
        self.timeout = timeout
        self.client = httpx.Client(base_url=base, timeout=timeout)
        self.ok_count = 0
        self.fail_count = 0

    @property
    def base(self) -> str:
        return str(self.client.base_url)

    @property
    def ws_base(self) -> str:
        u = self.client.base_url
        return f"ws://{u.host}:{u.port or DEFAULT_PORT}"

    def close(self):
        try:
            self.client.close()
        except Exception as e:                       # noqa: BLE001 - 정리 경로
            fail("세션 종료 중 오류", e)

    def reopen(self, base: str):
        self.close()
        self.client = httpx.Client(base_url=base, timeout=self.timeout)


def check_alive(s: Session) -> bool:
    """health + system status 를 확인하고 콘솔에 요약을 찍는다."""
    try:
        r = s.client.get("/health")
        r.raise_for_status()
    except httpx.HTTPError as e:
        fail(f"접속 실패: {s.base}", e)
        return False
    try:
        body = s.client.get("/api/system/status").json()
        d = body.get("data") or {}
        state = d.get("motion_state")
        info(f"연결됨 {C.bold(s.base)}  state={state} "
             f"ipc={d.get('ipc_connected')} cam={d.get('camera_connected')} "
             f"alarms={d.get('active_alarms')}")
        if state in (5, 6):
            warn(f"장비가 state={state} ({'FAULT' if state == 5 else 'ESTOP'}) 입니다 — "
                 f"모션 명령 전에 reset 이 필요합니다")
    except Exception as e:                           # noqa: BLE001 - 진단 출력
        fail("system.status 조회 실패 (연결은 살아 있음)", e)
    return True


def normalize_base(value: str, port: int = DEFAULT_PORT) -> str:
    """'192.168.0.42' · '192.168.0.42:8000' · 'http://…' 을 모두 base URL 로."""
    v = value.strip().rstrip("/")
    if "://" not in v:
        v = f"http://{v}" if ":" in v else f"http://{v}:{port}"
    return v


def _pick(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


# ───────────────────────────────────────────────────────────── WiFi 자동 탐색

CACHE_FILE = os.path.join(os.path.expanduser("~"), ".obtest_base")


def cached_base() -> str | None:
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def save_base(base: str):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(base)
    except OSError as e:
        warn(f"접속 주소 캐시 저장 실패 ({CACHE_FILE}): {e}")


def local_subnets() -> list[str]:
    """내 PC 가 붙어 있는 IPv4 대역들 (WiFi 포함) 의 /24 프리픽스."""
    import socket
    ips = set()
    try:                                   # 기본 경로 인터페이스 (보통 WiFi)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))         # 실제 트래픽은 나가지 않음
        ips.add(s.getsockname()[0])
        s.close()
    except OSError as e:
        warn(f"기본 인터페이스 IP 조회 실패: {e}")
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted({".".join(ip.split(".")[:3]) for ip in ips
                   if not ip.startswith(("127.", "169.254."))})


def scan_subnet(prefix: str, port: int, timeout: float = 0.4) -> list[str]:
    """대역 전체에 포트를 두드려 응답하는 호스트를 모은다."""
    import socket
    from concurrent.futures import ThreadPoolExecutor

    def probe(n: int) -> str | None:
        host = f"{prefix}.{n}"
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return host
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=128) as ex:
        return [h for h in ex.map(probe, range(1, 255)) if h]


def looks_like_device(base: str, timeout: float = 2.0) -> bool:
    """포트가 열린 것과 Ortho-Bender 인 것은 다르다 — /health 로 확인."""
    try:
        r = httpx.get(base + "/health", timeout=timeout)
        if r.status_code == 200 and "status" in r.json():
            return True
    except Exception:                                # noqa: BLE001 - 탐색 중 실패는 무시
        pass
    try:
        r = httpx.get(base + "/api/system/status", timeout=timeout)
        return r.status_code == 200 and "success" in r.json()
    except Exception:                                # noqa: BLE001
        return False


def discover(port: int, subnets: list[str] | None = None) -> list[str]:
    """현재 네트워크(WiFi)에서 장비를 찾는다."""
    nets = subnets or local_subnets()
    if not nets:
        fail("내 PC 의 네트워크 대역을 알 수 없습니다 — --host 로 직접 지정하세요")
        return []
    found = []
    for prefix in nets:
        info(f"{prefix}.0/24 스캔 중 … (포트 {port})")
        hosts = scan_subnet(prefix, port)
        for h in hosts:
            base = f"http://{h}:{port}"
            if looks_like_device(base):
                ok(f"장비 발견: {base}")
                found.append(base)
            else:
                print(C.dim(f"    {h}:{port} 열려 있으나 Ortho-Bender 아님"))
    if not found:
        fail(f"{', '.join(n + '.0/24' for n in nets)} 에서 장비를 찾지 못했습니다")
    return found


def wifi_target(s: Session, port: int) -> str | None:
    """장비에게 WiFi IP 를 물어본다."""
    try:
        body = s.client.get("/api/wifi/status").json()
    except httpx.HTTPError as e:
        fail("WiFi 상태 조회 실패", e)
        return None
    if not body.get("success", True):
        fail(f"WiFi 상태 조회 실패: [{body.get('code')}] {body.get('error')}")
        return None
    w = body.get("data") or {}
    ip = _pick(w, "ip", "ip_address", "address", "ipv4")
    ssid = _pick(w, "ssid", "SSID")
    rssi = _pick(w, "rssi", "RSSI", "signal")
    if not ip:
        warn(f"WiFi 미연결로 보입니다 — /api/wifi/status = {w}")
        return None
    info(f"WiFi ssid={ssid!r} rssi={rssi} ip={ip}")
    return f"http://{ip}:{port}"


def connect(args) -> Session | None:
    """WiFi 접속이 기본. 필요하면 유선으로 붙어 WiFi IP 를 받아 전환한다."""
    if args.host:
        candidates = [normalize_base(args.host, args.port)]
    elif args.base:
        candidates = [normalize_base(args.base, args.port)]
    else:
        candidates = [c for c in (os.environ.get("OB_BASE"), cached_base(), DEFAULT_WIRED)
                      if c]

    if args.scan:                                    # 탐색부터 하고 싶을 때
        candidates = discover(args.port, args.subnet) + candidates

    def try_open(base: str) -> Session | None:
        info(f"접속 시도: {base}")
        try:
            cand = Session(base, args.timeout)
        except httpx.InvalidURL as e:
            fail(f"잘못된 주소: {base}", e)
            return None
        if check_alive(cand):
            return cand
        cand.close()
        return None

    s = None
    seen = []
    for base in candidates:
        if base in seen:
            continue
        seen.append(base)
        s = try_open(base)
        if s:
            break

    if s is None and not args.host and not args.scan:
        # 유선 부트스트랩이 안 되는 상황 = 보통 WiFi 로만 붙어 있는 경우.
        warn("등록된 주소로 붙지 못했습니다 — 현재 네트워크(WiFi)에서 장비를 찾습니다")
        for base in discover(args.port, args.subnet):
            s = try_open(base)
            if s:
                break

    if s is None:
        fail("장비에 접속하지 못했습니다.\n"
             "  · WiFi IP 를 알면:  obtest.py --host <ip>\n"
             "  · 찾게 하려면:      obtest.py --scan  (또는 --subnet 192.168.0)\n"
             "  · 유선이라면:       obtest.py --host 192.168.77.2")
        return None

    if args.no_wifi:
        return s

    target = wifi_target(s, args.port)              # WiFi 가 기본 경로
    if not target:
        warn(f"WiFi 전환을 건너뛰고 현재 세션({s.base})을 사용합니다")
        save_base(s.base)
        return s
    if httpx.URL(target).host == s.client.base_url.host:
        info("이미 WiFi 주소로 접속되어 있습니다")
        save_base(s.base)
        return s

    info(f"WiFi 세션으로 전환: {s.base} → {target}")
    prev = s.base
    s.reopen(target)
    if not check_alive(s):
        fail(f"WiFi 주소({target})에 붙지 못했습니다 — {prev} 로 되돌립니다")
        s.reopen(prev)
        if not check_alive(s):
            return None
    save_base(s.base)
    return s


# ───────────────────────────────────────────────────────────── 실행

def show_response(r: httpx.Response, elapsed_ms: float) -> bool:
    """envelope 을 해석해 결과를 찍는다. 성공 여부를 반환."""
    tag = f"HTTP {r.status_code} · {elapsed_ms:.0f} ms"
    ctype = r.headers.get("content-type", "")

    if r.status_code == 422:                        # FastAPI 스키마 검증 실패
        fail(f"{tag} — 요청 스키마 검증 실패 (범위/타입 확인)")
        try:
            dump(r.json())
        except Exception:                           # noqa: BLE001
            _err(r.text)
        return False
    if r.status_code >= 500:
        fail(f"{tag} — 서버 오류")
        _err(r.text[:2000])
        return False

    if "application/json" not in ctype:
        fail(f"{tag} — 예상과 다른 Content-Type: {ctype or '없음'}")
        _err(r.text[:1000])
        return False

    body = r.json()
    if not isinstance(body, dict) or "success" not in body:   # /health 등
        ok(tag)
        dump(body)
        return True
    if body.get("success"):
        ok(tag)
        dump(body.get("data"))
        return True

    fail(f"{tag} — [{body.get('code')}] {body.get('error')}")
    if body.get("data") is not None:
        dump(body["data"])
    return False


def run_http(s: Session, cmd: Cmd, kv: dict) -> bool:
    path = cmd.path
    for p in cmd.path_params:
        if p not in kv:
            fail(f"{cmd.name}: 경로 인자 '{p}' 가 필요합니다  (help {cmd.name})")
            return False
        path = path.replace("{" + p + "}", str(kv.pop(p)))

    out_file = kv.pop("out", None)
    seconds = kv.pop("seconds", 3)

    use_query = cmd.method in ("GET", "DELETE") or cmd.query
    kwargs = {"params": kv} if use_query else {"json": kv}
    shown = ("?" + "&".join(f"{k}={v}" for k, v in kv.items())) if (use_query and kv) else ""
    info(f"{C.bold(cmd.method)} {path}{shown}" + ("" if use_query else f"  body={json.dumps(kv, ensure_ascii=False)}"))

    t0 = time.perf_counter()
    try:
        if cmd.kind == "stream":
            return run_stream(s, path, kv, float(seconds), out_file)
        r = s.client.request(cmd.method, path, **kwargs)
    except httpx.TimeoutException as e:
        fail(f"타임아웃 ({s.timeout}s) — 대기열이 길거나 장비가 응답하지 않습니다", e)
        return False
    except httpx.HTTPError as e:
        fail("요청 실패 (네트워크/연결)", e)
        return False
    ms = (time.perf_counter() - t0) * 1000

    if cmd.kind == "binary" and r.status_code == 200 and \
            "application/json" not in r.headers.get("content-type", ""):
        name = out_file or f"{cmd.name.replace('.', '_')}_{int(time.time())}.jpg"
        try:
            with open(name, "wb") as f:
                f.write(r.content)
        except OSError as e:
            fail(f"파일 저장 실패: {name}", e)
            return False
        ok(f"HTTP {r.status_code} · {ms:.0f} ms · {len(r.content):,} bytes → {name}")
        return True

    return show_response(r, ms)


def run_stream(s: Session, path: str, params: dict, seconds: float, out_file) -> bool:
    """MJPEG 를 잠깐 받아보고 프레임 수를 센다."""
    info(f"MJPEG {seconds}초 수신 중 …")
    frames, nbytes, first = 0, 0, None
    t0 = time.perf_counter()
    try:
        with s.client.stream("GET", path, params=params, timeout=seconds + 10) as r:
            if r.status_code != 200:
                r.read()
                return show_response(r, (time.perf_counter() - t0) * 1000)
            buf = b""
            for chunk in r.iter_bytes():
                buf += chunk
                nbytes += len(chunk)
                while True:
                    a = buf.find(b"\xff\xd8")          # JPEG SOI
                    b = buf.find(b"\xff\xd9", a + 2)   # EOI
                    if a < 0 or b < 0:
                        break
                    if first is None:
                        first = buf[a:b + 2]
                    frames += 1
                    buf = buf[b + 2:]
                if time.perf_counter() - t0 >= seconds:
                    break
    except httpx.HTTPError as e:
        fail("스트림 수신 실패", e)
        return False
    el = time.perf_counter() - t0
    ok(f"{frames} frames / {el:.1f}s = {frames / el if el else 0:.1f} fps, {nbytes:,} bytes")
    if first:
        name = out_file or f"stream_{int(time.time())}.jpg"
        try:
            with open(name, "wb") as f:
                f.write(first)
            info(f"첫 프레임 저장 → {name}")
        except OSError as e:
            fail(f"파일 저장 실패: {name}", e)
    return frames > 0


def run_ws(s: Session, cmd: Cmd, kv: dict) -> bool:
    try:
        import asyncio
        import websockets
    except ImportError as e:
        fail("websockets 패키지가 필요합니다:  pip install websockets", e)
        return False

    seconds = float(kv.get("seconds", 5))
    url = s.ws_base + cmd.path
    info(f"{C.bold('WS')} {url}  ({seconds}초 구독)")

    async def go():
        count, types = 0, {}
        try:
            async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
                t0 = time.perf_counter()
                while time.perf_counter() - t0 < seconds:
                    left = seconds - (time.perf_counter() - t0)
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=max(left, 0.1))
                    except asyncio.TimeoutError:
                        break
                    count += 1
                    try:
                        msg = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        print(C.dim(f"  [{count}] non-JSON {len(raw)} bytes"))
                        continue
                    types[msg.get("type")] = types.get(msg.get("type"), 0) + 1
                    if count <= 3 or count % 50 == 0:      # 샘플만 출력
                        if isinstance(msg.get("frame_b64"), str):
                            msg = dict(msg)
                            msg["frame_b64"] = f"<{len(msg['frame_b64'])} chars>"
                        print(C.dim(f"  [{count}] ") +
                              json.dumps(msg, ensure_ascii=False)[:400])
                el = time.perf_counter() - t0
                ok(f"{count} frames / {el:.1f}s = {count / el if el else 0:.1f} Hz  types={types}")
                return count > 0
        except Exception as e:                           # noqa: BLE001 - 모든 WS 오류 표시
            fail(f"WebSocket 오류 ({url})", e)
            return False

    return asyncio.run(go())


def load_feed_cal():
    """저장된 FEED 환산 계수를 읽는다."""
    global MM_PER_DEG
    try:
        with open(FEED_CAL_FILE, encoding="utf-8") as f:
            MM_PER_DEG = float(json.load(f)["mm_per_deg"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        MM_PER_DEG = None
    return MM_PER_DEG


def save_feed_cal(mm_per_deg: float):
    try:
        with open(FEED_CAL_FILE, "w", encoding="utf-8") as f:
            json.dump({"mm_per_deg": mm_per_deg}, f)
        info(f"환산 계수 저장 → {FEED_CAL_FILE}")
    except OSError as e:
        warn(f"환산 계수 저장 실패: {e}")


def feed_factor(kv: dict):
    """(mm_per_deg, 출처) 를 정한다. 추측값이면 경고한다."""
    import math
    if "mmdeg" in kv:
        return float(kv["mmdeg"]), "인자 mmdeg"
    if "roller" in kv:
        d = float(kv["roller"])
        return math.pi * d / 360.0, f"롤러 Ø{d} mm 가정"
    if MM_PER_DEG:
        return MM_PER_DEG, "실측 교정값"
    return math.pi * ROLLER_MM / 360.0, f"⚠ 미교정 — 롤러 Ø{ROLLER_MM} mm 추측"


class Tracer:
    """이동 중 FEED 위치를 폴링해 오버슈트·역회전을 잡아낸다."""

    def __init__(self, s: Session, hz: float = 20.0):
        self.s, self.dt = s, 1.0 / hz
        self.samples: list[tuple[float, float, object]] = []
        self._stop = False
        self._t = None

    def start(self):
        import threading
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        t0 = time.perf_counter()
        while not self._stop:
            try:
                st = call_data(self.s, "GET", "/api/motor/status")
                a = {x["axis"]: x for x in st.get("axes", [])}.get(0)
                if a:
                    self.samples.append((time.perf_counter() - t0,
                                         float(a["position"]),
                                         (a.get("signals") or {}).get("dir")))
            except Exception:                       # noqa: BLE001 - 샘플링 실패는 무시
                pass
            time.sleep(self.dt)

    def stop(self):
        self._stop = True
        if self._t:
            self._t.join(timeout=2)

    def report(self, start: float, target: float, mm_per_deg: float, unit: str):
        if len(self.samples) < 3:
            warn(f"트레이스 샘플이 부족합니다 ({len(self.samples)}개) — "
                 f"이동이 너무 짧거나 폴링이 따라가지 못했습니다")
            return
        sign = 1.0 if target >= start else -1.0
        peak = max(self.samples, key=lambda r: r[1] * sign)
        final = self.samples[-1][1]
        overshoot = (peak[1] - target) * sign
        backtrack = (peak[1] - final) * sign
        dirs = [r[2] for r in self.samples if r[2] not in (None, 0)]
        flipped = any(d * sign < 0 for d in dirs if isinstance(d, (int, float)))

        print(C.bold("\n  이동 트레이스"))
        step = max(1, len(self.samples) // 12)
        for t, pos, d in self.samples[::step]:
            bar = "▏" * min(40, int(abs(pos - start) / max(abs(target - start), 1e-9) * 40))
            print(f"   {t:5.2f}s  {pos:9.3f} deg  dir={str(d):>4}  {C.dim(bar)}")

        print(f"\n   목표      : {target:9.3f} deg")
        print(f"   최대 도달 : {peak[1]:9.3f} deg  (t={peak[0]:.2f}s)")
        print(f"   최종      : {final:9.3f} deg")
        if overshoot > 0.02:
            mm = overshoot * mm_per_deg if unit != "deg" else 0.0
            fail(f"오버슈트 {overshoot:+.3f} deg" + (f" (≈{mm:+.3f} mm)" if unit != "deg" else "")
                 + f" 후 {backtrack:.3f} deg 역회전 — "
                 "목표를 지나쳤다가 되돌아오는 보정 동작입니다")
            info("  → 감속 거리가 부족합니다. decel 을 낮추거나 shape=linear, "
                 "speed 를 낮춰 보세요. mode=move (상대 이동) 로 보정 루프를 피할 수도 있습니다")
        elif backtrack > 0.02:
            fail(f"오버슈트 없이 {backtrack:.3f} deg 역회전 — "
                 "목표에 도달한 뒤 되돌아왔습니다 (도달 판정 보정 또는 홀딩 토크 부족)")
            info("  → protection 의 axes.0.hold_enabled/hold_cs 를 확인하세요")
        elif flipped:
            warn("위치는 되돌아오지 않았지만 dir 신호에 역방향이 잡혔습니다 "
                 "(2 스텝 이내 미세 보정으로 보입니다)")
        else:
            ok("오버슈트·역회전 없음 — 눈에 보이는 되돌림은 기구적 백래시/와이어 스프링백 쪽입니다")


def wait_feed_idle(s: Session, timeout: float):
    """FEED 이동이 끝날 때까지 기다리고 최종 상태를 돌려준다."""
    deadline = time.perf_counter() + timeout
    while True:
        st = call_data(s, "GET", "/api/motor/status")
        lim = call_data(s, "GET", "/api/motor/limits")
        state, queued = st.get("state"), lim.get("queued", 0)
        if state == 0 and not queued:
            return st
        if state in (5, 6):
            raise ObFailure(f"이송 중 state={state} "
                            f"({'FAULT' if state == 5 else 'ESTOP'}) 발생")
        if time.perf_counter() > deadline:
            raise ObFailure(f"완료 대기 시간 초과 ({timeout}s) — queued={queued}, state={state}")
        time.sleep(0.2)


def feed_position(s: Session) -> float:
    st = call_data(s, "GET", "/api/motor/status")
    axes = {a["axis"]: a for a in st.get("axes", [])}
    if 0 not in axes:
        raise ObFailure("응답에 FEED(axis 0) 축이 없습니다")
    return float(axes[0]["position"])


def run_feed_cal(s: Session, kv: dict) -> bool:
    """FEED 를 정해진 각도만큼 돌리고, 실제 배출된 와이어 길이로 계수를 구한다.

    feed.cal 60                 → 60 deg 돌린 뒤 측정값을 입력받음
    feed.cal 60 measured=87.3   → 측정값을 미리 주고 계산만
    """
    import math
    deg = float(kv.get("deg", 60))
    speed = float(kv.get("speed", 20))
    try:
        start = feed_position(s)
        info(f"FEED 를 {deg:+.3f} deg 돌립니다 ({start:.3f} → {start + deg:.3f})")
        call_data(s, "POST", "/api/motor/move_to",
                  json={"axis": 0, "position": start + deg, "speed": speed})
        st = wait_feed_idle(s, s.timeout)
        axes = {a["axis"]: a for a in st.get("axes", [])}
        moved = float(axes[0]["position"]) - start
        info(f"실제 회전량: {moved:+.3f} deg")
        if abs(moved) < 1e-6:
            fail("축이 움직이지 않았습니다 — 교정할 수 없습니다")
            return False

        measured = kv.get("measured")
        if measured is None:
            try:
                measured = input(C.yel("배출된 와이어 길이를 mm 로 입력하세요 (캘리퍼 측정): "))
            except EOFError:
                fail("측정값 입력이 없습니다 — measured=<mm> 로 다시 실행하세요")
                return False
        mm_per_deg = float(measured) / moved
        ok(f"환산 계수 = {mm_per_deg:.6f} mm/deg  "
           f"(1 회전 {mm_per_deg * 360:.2f} mm ≡ 롤러 Ø{mm_per_deg * 360 / math.pi:.2f} mm)")
        save_feed_cal(mm_per_deg)
        global MM_PER_DEG
        MM_PER_DEG = mm_per_deg
        info(f"이제 feed 5 는 {5 / mm_per_deg:.3f} deg 를 지령합니다")
        return True
    except (ValueError, TypeError) as e:
        fail("측정값이 숫자가 아닙니다", e)
        return False
    except ObFailure as e:
        fail(str(e))
        return False
    except httpx.HTTPError as e:
        fail("교정 중 통신 오류", e)
        return False


# ─────────────────────────────── TMC260C 마이크로스텝 (DRVCTRL.MRES)

# TMC26x DRVCTRL (SDOFF=0, STEP/DIR 모드)
#   bit 9   INTPOL  — 256 마이크로스텝 보간 (부드러워질 뿐 분해능은 안 늘어남)
#   bit 8   DEDGE   — STEP 양 에지 사용
#   bit 3:0 MRES    — 마이크로스텝 분해능
MRES_TO_USTEPS = {0: 256, 1: 128, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4, 7: 2, 8: 1}
USTEPS_TO_MRES = {v: k for k, v in MRES_TO_USTEPS.items()}


def decode_drvctrl(val: int) -> dict:
    code = val & 0xF
    return {"raw": val, "mres": code, "microsteps": MRES_TO_USTEPS.get(code),
            "intpol": bool((val >> 9) & 1), "dedge": bool((val >> 8) & 1)}


def read_drvctrl(s: Session, driver: str) -> int | None:
    """이름으로 덤프해서 DRVCTRL 값을 얻는다 (TMC26x 는 write-only 라 서버 shadow 값)."""
    d = call_data(s, "GET", f"/api/motor/diag/dump/{driver}")
    regs = d.get("registers") or {}
    if "DRVCTRL" not in regs:
        fail(f"덤프에 DRVCTRL 이 없습니다 — 있는 레지스터: {', '.join(regs) or '없음'}")
        return None
    return int(str(regs["DRVCTRL"]), 16)


def find_reg_addr(s: Session, driver: str, want: int, span: int = 16) -> int | None:
    """{addr} 매핑이 문서화되어 있지 않으므로, 읽어서 값이 일치하는 주소를 찾는다."""
    info(f"DRVCTRL(0x{want:05X}) 에 해당하는 addr 를 0x00–0x{span - 1:02X} 에서 탐색 …")
    for a in range(span):
        try:
            r = call_data(s, "GET", f"/api/motor/diag/register/{driver}/{a}")
        except (ObFailure, httpx.HTTPError):
            continue
        v = r.get("value")
        if isinstance(v, int) and v == want:
            ok(f"addr 0x{a:02X} = 0x{v:05X} (DRVCTRL 과 일치)")
            return a
    fail("DRVCTRL 과 값이 일치하는 addr 를 찾지 못했습니다 — addr=<주소> 로 직접 지정하세요")
    return None


def run_mstep(s: Session, kv: dict) -> bool:
    """마이크로스텝 조회/변경.

    mstep                          현재 설정 디코드 (읽기 전용)
    mstep 64                       64 마이크로스텝으로 변경 + steps_per_unit 자동 스케일
    mstep 64 addr=0x00 axis=0 calib=false
    """
    driver = str(kv.get("driver", "tmc260c_0"))
    axis = int(kv.get("axis", 0))
    try:
        cur = read_drvctrl(s, driver)
        if cur is None:
            return False
        d = decode_drvctrl(cur)
        info(f"{driver} DRVCTRL = 0x{cur:05X}")
        print(f"   MRES     : {d['mres']} → {d['microsteps']} 마이크로스텝/풀스텝")
        print(f"   INTPOL   : {d['intpol']}  (보간 — 부드러움만, 분해능 아님)")
        print(f"   DEDGE    : {d['dedge']}")

        calib = call_data(s, "GET", "/api/motor/calibration")
        spu = float(calib.get("steps_per_unit", {}).get(str(axis), 0) or 0)
        lim = float(calib.get("speed_limit", {}).get(str(axis), 0) or 0)
        print(f"   축 {axis}    : steps_per_unit={spu}  speed_limit={lim} /s")

        target = kv.get("microsteps")
        if target is None:
            if d["microsteps"] == 256:
                warn("이미 최대(256 마이크로스텝)입니다 — 드라이버로는 더 올릴 수 없습니다. "
                     "분해능을 더 얻으려면 기구 감속비를 바꿔야 합니다")
            else:
                info(f"변경하려면:  mstep {min(256, (d['microsteps'] or 1) * 4)}")
            return True

        target = int(target)
        if target not in USTEPS_TO_MRES:
            fail(f"지원하지 않는 값: {target} — {sorted(USTEPS_TO_MRES)} 중에서 고르세요")
            return False
        if target == d["microsteps"]:
            info("이미 그 값입니다 — 변경하지 않습니다")
            return True

        new = (cur & ~0xF) | USTEPS_TO_MRES[target]      # MRES 만 교체, 나머지 비트 보존
        ratio = target / d["microsteps"]
        new_spu = spu * ratio
        print()
        warn("드라이버 레지스터를 직접 씁니다 — 서버 안전 가드는 CS·TOFF 에만 걸려 있습니다")
        print(f"   DRVCTRL        0x{cur:05X} → 0x{new:05X}")
        print(f"   마이크로스텝    {d['microsteps']} → {target}  (×{ratio:g})")
        print(f"   steps_per_unit {spu} → {new_spu}  "
              f"{'(자동 적용)' if kv.get('calib', True) else '(적용 안 함)'}")
        print(f"   speed_limit    {lim} → {lim / ratio:.3f} /s  "
              f"(8kHz ÷ steps_per_unit — 최고 속도가 {ratio:g}배 낮아집니다)")

        st = call_data(s, "GET", "/api/motor/status")
        if st.get("state") != 0:
            fail(f"축이 IDLE 이 아닙니다 (state={st.get('state')}) — 정지 후 다시 실행하세요")
            return False

        addr = kv.get("addr")
        addr = int(str(addr), 0) if addr is not None else find_reg_addr(s, driver, cur)
        if addr is None:
            return False

        try:
            if input(C.yel(f"\n0x{new:05X} 를 {driver} addr 0x{addr:02X} 에 쓸까요? [y/N] ")
                     ).strip().lower() != "y":
                info("취소했습니다")
                return True
        except EOFError:
            fail("확인 입력이 없어 중단합니다 (비대화형에서는 실행하지 않습니다)")
            return False

        call_data(s, "POST", f"/api/motor/diag/register/{driver}/{addr}", json={"value": new})
        back = read_drvctrl(s, driver)
        got = decode_drvctrl(back or 0)
        if got["microsteps"] != target:
            fail(f"쓰기 후 읽은 값이 다릅니다: 0x{back:05X} "
                 f"(MRES={got['mres']} → {got['microsteps']} 마이크로스텝)")
            return False
        ok(f"마이크로스텝 {target} 적용 (DRVCTRL=0x{back:05X})")

        if kv.get("calib", True):
            call_data(s, "POST", "/api/motor/calibration",
                      json={"axis": axis, "steps_per_unit": new_spu})
            ok(f"steps_per_unit {spu} → {new_spu} 적용")
        else:
            warn(f"steps_per_unit 을 {new_spu} 로 직접 바꿔야 이동량이 맞습니다")

        info("다음 순서: feed.cal 로 재실측 → feed.step 으로 최소 이동 확인 → profiles 의 accel 확인")
        return True
    except ObFailure as e:
        fail(str(e))
        return False
    except httpx.HTTPError as e:
        fail("마이크로스텝 변경 중 통신 오류", e)
        return False


def feed_resolution(s: Session, mm_per_deg: float):
    """(deg/step, mm/step) — 축이 물리적으로 낼 수 있는 최소 이동."""
    calib = call_data(s, "GET", "/api/motor/calibration")
    spu = float(calib.get("steps_per_unit", {}).get("0", 0) or 0)
    if spu <= 0:
        return None, None
    return 1.0 / spu, mm_per_deg / spu


def run_feed_step(s: Session, kv: dict) -> bool:
    """같은 양을 여러 번 반복 이송한다.

    feed.step 0.01 count=20            → 0.01 mm 씩 20회
    feed.step 0.01 count=20 delay=0.5 speed=5
    feed.step 0.1 count=20 snap=true   → 0.1 mm 를 가장 가까운 정수 스텝으로
                                          스냅해 매회 '완전히 같은' 스텝 수로
                                          이송 (등간격 우선, 스케일은 실제
                                          양자 크기를 따라감)
    """
    step_mm = kv.get("mm")
    if step_mm is None:
        fail("사용법: feed.step <1회 이송 mm> [count=20] [delay=초] [speed=..] [mmps=..]")
        return False
    try:
        step_mm = float(step_mm)
        count = int(kv.get("count", 20))
        delay = float(kv.get("delay", 0.3))
    except (TypeError, ValueError) as e:
        fail("인자가 숫자가 아닙니다", e)
        return False

    unit = str(kv.get("unit", "wire"))
    mm_per_deg, source = feed_factor(kv)
    step_deg = step_mm if unit == "deg" else step_mm / mm_per_deg

    try:
        deg_per_step, mm_per_step = feed_resolution(s, mm_per_deg)
        snap = str(kv.get("snap", "")).lower() in ("1", "true", "yes")
        if snap and deg_per_step:
            # 등간격 모드: 지령을 가장 가까운 '정수 스텝'으로 스냅한다.
            # 매회 이동이 완전히 동일해지는 대신, 1회 이동량은 0.1 mm 가
            # 아니라 스텝 양자의 정수배가 된다 — steps/mm 분모의 pi 때문에
            # 두 그리드는 원리적으로 통약 불가능하므로(등간격 vs 평균 정확)
            # 여기서는 등간격을 택한 것이다. 누적 좌표도 스냅된 양자로
            # 세므로 회차 간 오차 이월이 없다.
            n_snap = max(1, round(abs(step_deg) / deg_per_step))
            snapped = n_snap * deg_per_step * (1 if step_deg >= 0 else -1)
            info(f"snap: {step_mm:+.4f} mm ({abs(step_deg) / deg_per_step:.2f} step) "
                 f"→ {n_snap} step = {snapped * mm_per_deg:+.5f} mm 등간격 "
                 f"(스케일 {100 * (snapped * mm_per_deg / step_mm - 1):+.2f}%)")
            step_deg = snapped
            step_mm = snapped * mm_per_deg
        if mm_per_step:
            n_steps = abs(step_deg) / deg_per_step
            info(f"축 분해능: {deg_per_step:.5f} deg/step = {mm_per_step:.5f} mm/step")
            info(f"1회 지령 {step_mm:+.4f} mm = {step_deg:+.5f} deg = {n_steps:.2f} step")
            if n_steps < 1:
                fail(f"1회 이송이 1 step 보다 작습니다 ({n_steps:.2f} step) — "
                     f"이 장비에서 낼 수 없는 이동량입니다")
                info(f"  → 최소 이송 단위는 {mm_per_step:.5f} mm 입니다. "
                     f"이 값의 배수로 지령하거나 캘리브레이션(마이크로스텝)을 높이세요")
                return False
            if n_steps < 2:
                warn(f"1회 이송이 {n_steps:.2f} step 으로 도달 판정 허용오차(2 step "
                     f"= {2 * mm_per_step:.5f} mm) 안에 들어갑니다 — "
                     f"move_to 가 '이미 도달' 로 보고 움직이지 않을 수 있습니다")
                info("  → 아래는 절대 좌표 그리드로 누적 지령하므로 오차가 쌓이지는 않습니다")

        start = feed_position(s)
        info(f"시작 위치 {start:.4f} deg — {step_mm:+.4f} mm × {count}회 "
             f"(총 {step_mm * count:+.3f} mm)")

        speed = (float(kv["mmps"]) / mm_per_deg if ("mmps" in kv and unit != "deg")
                 else float(kv.get("speed", 5.0)))

        moved_prev = start
        results = []
        for i in range(1, count + 1):
            target = start + step_deg * i          # 절대 그리드 — 반올림 오차가 누적되지 않음
            call_data(s, "POST", "/api/motor/move_to",
                      json={"axis": 0, "position": target, "speed": speed})
            st = wait_feed_idle(s, s.timeout)
            pos = float({a["axis"]: a for a in st["axes"]}[0]["position"])
            d_deg = pos - moved_prev
            results.append(d_deg)
            print(f"   {i:2d}/{count}  목표 {target:9.4f}  실제 {pos:9.4f} deg  "
                  f"이번 이동 {d_deg:+.5f} deg" +
                  (f" ≈ {d_deg * mm_per_deg:+.5f} mm" if unit != "deg" else ""))
            moved_prev = pos
            if delay:
                time.sleep(delay)

        total_deg = moved_prev - start
        expect = step_deg * count
        zero = sum(1 for d in results if abs(d) < 1e-6)
        ok(f"총 {total_deg:+.4f} deg (목표 {expect:+.4f}, 오차 {total_deg - expect:+.5f})"
           + (f" ≈ {total_deg * mm_per_deg:+.4f} mm" if unit != "deg" else ""))
        if zero:
            fail(f"{zero}/{count} 회는 전혀 움직이지 않았습니다 — 1회 이송량이 분해능/"
                 f"도달 허용오차보다 작습니다")
            return False
        return True
    except ObFailure as e:
        fail(str(e))
        return False
    except httpx.HTTPError as e:
        fail("반복 이송 중 통신 오류", e)
        return False


def run_feed(s: Session, kv: dict) -> bool:
    """피더를 mm 단위로 이송한다 (FEED 축의 API 단위는 deg 라서 환산이 필요).

    feed 5                  → 5 mm 이송 (실측 교정값 사용)
    feed 5 speed=20
    feed 5 mmdeg=1.745      → 계수를 직접 지정
    feed -3 unit=deg        → 환산 없이 -3 deg
    """
    mm = kv.get("mm")
    if mm is None:
        fail("사용법: feed <mm> [speed=..] [mmdeg=<mm/deg>] [unit=mm|deg]\n"
             "  계수를 모르면 먼저:  feed.cal 60")
        return False
    try:
        mm = float(mm)
    except (TypeError, ValueError):
        fail(f"이송량이 숫자가 아닙니다: {mm!r}")
        return False

    unit = str(kv.get("unit", "wire"))          # wire = mm 이송, deg = 축 각도 그대로
    mm_per_deg, source = feed_factor(kv)
    mode = str(kv.get("mode", "move_to"))       # move_to = 절대, move = 상대(보정 루프 없음)

    if "mmps" in kv and unit != "deg":          # 초당 mm 로 속도 지정
        speed = float(kv["mmps"]) / mm_per_deg
        info(f"속도 {kv['mmps']} mm/s → {speed:.3f} deg/s")
    else:
        speed = float(kv.get("speed", 20.0))

    if unit == "deg":
        delta = mm
        info(f"FEED {delta:+.3f} deg (환산 없음)")
    else:
        if mm_per_deg <= 0:
            fail(f"환산 계수가 잘못되었습니다: {mm_per_deg}")
            return False
        delta = mm / mm_per_deg
        info(f"FEED {mm:+.3f} mm → {delta:+.3f} deg "
             f"({mm_per_deg:.6f} mm/deg · {source})")
        if MM_PER_DEG is None and "mmdeg" not in kv and "roller" not in kv:
            warn("환산 계수가 교정되지 않았습니다 — 이송량이 맞지 않으면 "
                 "'feed.cal 60' 으로 실측하세요")

    try:
        start = feed_position(s)

        calib = call_data(s, "GET", "/api/motor/calibration")
        limit = float(calib.get("speed_limit", {}).get("0", speed))
        if speed > limit:
            warn(f"speed {speed} → {limit} deg/s 로 클램프 (축 speed_limit)")
            speed = limit

        target = start + delta
        tracer = None
        if kv.get("trace"):
            tracer = Tracer(s, hz=float(kv.get("hz", 20)))
            tracer.start()

        if mode == "move":
            info(f"move axis=0 distance={delta:+.4f} deg @ {speed:.3f} deg/s "
                 f"(상대 이동 — 도달 보정 루프 없음)")
            call_data(s, "POST", "/api/motor/move",
                      json={"axis": 0, "distance": delta, "speed": speed})
        else:
            info(f"move_to axis=0 {start:.3f} → {target:.3f} deg @ {speed:.3f} deg/s")
            call_data(s, "POST", "/api/motor/move_to",
                      json={"axis": 0, "position": target, "speed": speed})

        st = wait_feed_idle(s, s.timeout)
        if tracer:
            tracer.stop()
            tracer.report(start, target, mm_per_deg, unit)
        axes = {a["axis"]: a for a in st.get("axes", [])}
        final = float(axes[0]["position"])
        err_deg = final - target
        err_mm = err_deg * mm_per_deg if unit != "deg" else 0.0
        tol = max(0.05, abs(delta) * 0.002)
        msg = (f"{final:.3f} deg (오차 {err_deg:+.3f} deg"
               + (f" ≈ {err_mm:+.3f} mm)" if unit != "deg" else ")"))
        if abs(err_deg) > tol:
            fail(f"목표 미도달: {msg} — 축이 막혔거나 잘렸는지 확인하세요")
            return False
        ok(f"완료: {msg}"
           + (f"  ≈ {(final - start) * mm_per_deg:+.3f} mm 배출" if unit != "deg" else ""))
        return True
    except ObFailure as e:
        fail(str(e))
        return False
    except httpx.HTTPError as e:
        fail("이송 중 통신 오류", e)
        return False


class ObFailure(RuntimeError):
    pass


def call_data(s: Session, method: str, path: str, **kw):
    """envelope 을 벗겨 data 만 돌려준다 (실패는 ObFailure)."""
    r = s.client.request(method, path, **kw)
    if r.status_code >= 400:
        raise ObFailure(f"{method} {path} → HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    if isinstance(body, dict) and "success" in body and not body["success"]:
        raise ObFailure(f"{method} {path} → [{body.get('code')}] {body.get('error')}")
    return body.get("data") if isinstance(body, dict) and "data" in body else body


def execute(s: Session, line: str) -> bool | None:
    """콘솔 한 줄을 실행. 내장 명령이면 None 을 반환."""
    try:
        tokens = shlex.split(line)
    except ValueError as e:
        fail("따옴표가 맞지 않습니다", e)
        return False
    if not tokens:
        return None

    head, rest = tokens[0], tokens[1:]

    # ── 내장 명령 ──
    if head in ("quit", "exit", "q"):
        raise EOFError
    if head in ("ls", "list", "cmds"):
        list_cmds(rest[0] if rest else None)
        return None
    if head in ("help", "?"):
        if rest:
            c = resolve(rest[0])
            if c:
                print_help(c)
        else:
            print(__doc__)
        return None
    if head == "base":
        if not rest:
            info(f"현재 base = {s.base}")
        else:
            try:
                s.reopen(normalize_base(rest[0]))
            except httpx.InvalidURL as e:
                fail(f"잘못된 주소: {rest[0]}", e)
                return False
            check_alive(s)
        return None
    if head == "reconnect":
        s.reopen(s.base)
        check_alive(s)
        return None
    if head in ("feed", "feed.cal", "feed.step"):       # 피더 편의 명령
        first = "deg" if head == "feed.cal" else "mm"
        kv = {}
        for i, t in enumerate(rest):
            if "=" in t:
                k, _, v = t.partition("=")
                kv[k.strip()] = parse_value(v)
            elif i == 0:
                kv[first] = parse_value(t)
        runner = {"feed": run_feed, "feed.cal": run_feed_cal, "feed.step": run_feed_step}[head]
        return runner(s, kv)
    if head == "mstep":                                # 마이크로스텝 조회/변경
        kv = {}
        for i, t in enumerate(rest):
            if "=" in t:
                k, _, v = t.partition("=")
                kv[k.strip()] = parse_value(v)
            elif i == 0:
                kv["microsteps"] = parse_value(t)
        return run_mstep(s, kv)
    if head == "discover":
        found = discover(DEFAULT_PORT if not rest else int(rest[0]))
        if found:
            info(f"연결하려면:  base {found[0]}")
        return None
    if head == "raw":
        if len(rest) < 2:
            fail("사용법: raw <METHOD> <경로> [k=v ...]")
            return False
        c = Cmd("raw", rest[0].upper(), rest[1])
        return run_http(s, c, parse_args(c, rest[2:]))
    if head == "ws":                                   # ws motor 5
        if not rest:
            fail("사용법: ws <motor|camera|system|diag> [초]")
            return False
        c = resolve("ws." + rest[0]) or resolve(rest[0])
        if not c or c.kind != "ws":
            fail(f"WebSocket 채널이 아닙니다: {rest[0]}")
            return False
        return run_ws(s, c, parse_args(c, rest[1:]))

    # ── API 명령 ──
    cmd = resolve(head)
    if cmd is None:
        return False
    kv = parse_args(cmd, rest)
    if cmd.kind == "ws":
        return run_ws(s, cmd, kv)
    return run_http(s, cmd, kv)


# ───────────────────────────────────────────────────────────── help 출력

def print_help(c: Cmd):
    print(f"\n  {C.bold(c.name)}   {C.dim(c.method + ' ' + c.path)}")
    if c.alias:
        print(f"  별칭   : {', '.join(c.alias)}")
    if c.params:
        print(f"  인자   : {' '.join(c.params)}")
    if c.path_params:
        print(f"  경로인자: {', '.join(c.path_params)} (필수)")
    if c.note:
        print(f"  설명   : {c.note}")
    where = "query" if (c.method in ("GET", "DELETE") or c.query) else "JSON body"
    print(f"  전송   : {where}")
    example = " ".join(f"{p}=…" for p in c.params[:3])
    print(f"  예시   : {c.name} {example}".rstrip() + "\n")


def list_cmds(pattern: str | None = None):
    groups: dict[str, list[Cmd]] = {}
    for c in CMDS:
        if pattern and pattern.lower() not in c.name.lower() and pattern.lower() not in c.path.lower():
            continue
        key = c.path.split("/")[2] if c.path.startswith("/api/") else c.path.split("/")[1]
        groups.setdefault(key, []).append(c)
    if not groups:
        warn(f"'{pattern}' 에 맞는 명령이 없습니다")
        return
    for key, items in groups.items():
        print(f"\n{C.bold('[' + key + ']')}")
        for c in items:
            args = " ".join(c.params)
            print(f"  {c.name:<20} {C.dim(c.method.ljust(6))} {args:<44} {C.dim(c.note)}")
    print()


def setup_readline():
    try:
        import readline
    except ImportError:
        return
    names = sorted(BY_NAME) + ["ls", "help", "quit", "raw", "ws", "base", "reconnect"]

    def completer(text, state):
        hits = [n for n in names if n.startswith(text)]
        return hits[state] + " " if state < len(hits) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(" \t\n")


# ───────────────────────────────────────────────────────────── main

def main() -> int:
    global VERBOSE
    p = argparse.ArgumentParser(
        description="Ortho-Bender 전체 API 테스트 콘솔 (WiFi 접속 기본)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="인자 없이 실행하면 대화형 콘솔, 명령을 주면 한 번 실행하고 종료합니다.",
    )
    p.add_argument("command", nargs="*", help="한 번만 실행할 명령과 인자")
    p.add_argument("--host", help="장비 IP 또는 URL (WiFi IP 를 알 때)")
    p.add_argument("--base", help="base URL 전체 지정")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--no-wifi", action="store_true", help="WiFi 자동 전환을 하지 않음")
    p.add_argument("--scan", action="store_true",
                   help="현재 네트워크(WiFi)를 스캔해 장비를 먼저 찾음")
    p.add_argument("--subnet", action="append",
                   help="스캔할 대역 프리픽스 (예: 192.168.0). 여러 번 지정 가능")
    p.add_argument("--mm-per-deg", type=float,
                   help="FEED 축 1도당 배출되는 와이어 mm (feed.cal 로 실측 가능)")
    p.add_argument("--roller", type=float, default=20.0,
                   help="롤러 직경 mm 로 환산 (--mm-per-deg 가 없을 때만 사용하는 추정치)")
    p.add_argument("--timeout", type=float, default=60.0, help="HTTP 타임아웃 (s)")
    p.add_argument("-v", "--verbose", action="store_true", help="에러 트레이스백 출력")
    args = p.parse_args()
    VERBOSE = args.verbose
    global ROLLER_MM, MM_PER_DEG
    ROLLER_MM = args.roller
    load_feed_cal()                                  # 저장된 실측 계수
    if args.mm_per_deg:
        MM_PER_DEG = args.mm_per_deg
    if MM_PER_DEG:
        info(f"FEED 환산 계수 {MM_PER_DEG:.6f} mm/deg "
             f"({'인자 지정' if args.mm_per_deg else FEED_CAL_FILE})")

    s = connect(args)
    if s is None:
        return 2

    try:
        if args.command:                                # 원샷 모드
            res = execute(s, " ".join(shlex.quote(t) for t in args.command))
            s.ok_count += int(res is True)
            s.fail_count += int(res is False)
            return 0 if res is not False else 1

        setup_readline()
        print(C.dim("\n명령을 입력하세요. ls = 목록, help <명령> = 도움말, quit = 종료 (tab 자동완성)\n"))
        while True:
            try:
                line = input(C.blu("ob> ")).strip()
            except KeyboardInterrupt:
                print("\n" + C.dim("(quit 으로 종료)"))
                continue
            if not line:
                continue
            try:
                res = execute(s, line)
            except EOFError:
                break
            except Exception as e:                      # noqa: BLE001 - 콘솔은 죽지 않는다
                fail("명령 실행 중 예외", e)
                res = False
            if res is True:
                s.ok_count += 1
            elif res is False:
                s.fail_count += 1
    except EOFError:
        pass
    finally:
        print()
        info(f"세션 종료 — 성공 {s.ok_count} · 실패 {s.fail_count}")
        s.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        raise SystemExit(130)
