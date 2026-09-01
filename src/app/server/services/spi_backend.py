"""
spi_backend.py — 테스트 벤치용 Linux spidev + gpiod 모터 백엔드.

i.MX8MP EVK + Veyron 1×2A ×3 (TMC260C-PA) 벤치에 대한 MotorBackend ABC
구현. DiagService(수동적 레지스터 접근)와, OB_MOTOR_BACKEND=spidev 일 때의
모터 서비스가 함께 쓴다.

# 검증된 동작 구성 (2026-05-08)
  - SPI: /dev/spidev1.0, mode 3 + SPI_NO_CS, 50 kHz
  - 3축 CS 라인 (수동 GPIO 토글):
      cs=0  →  LIFT  (gpio5_07, ECSPI1_MOSI alt5)
      cs=1  →  BEND  (gpio3_22, SAI5_RXD1 alt5)
      cs=2  →  FEED  (gpio5_13, ECSPI2_SS0 alt5)
  - STEP: SAI5_RXFS 패드의 PWM4 (pwmchip2/pwm0), 모든 칩에 병렬
  - DIR:  gpio3_23 (SAI5_RXD3 alt5), 모든 칩에 병렬

# 🚨 절대 안전 한계 (무효화 불가)
  - CS    ≤ 19   (CS=31 로 2026-05-08 보드 1/2층 소손)
  - TOFF  ≤ 8
  - CHOPCONF 기본값은 검증값 0x99548 로 동결
  - 초기화 순서 필수: SPI 먼저 → 500 us CS 안정화 → init 500x SEQ
  - 폴트 플래그(OT/S2G/OL)는 스텝 펄스 중 즉시 중단을 트리거

필요: python3-spidev, python3-gpiod >= 2.0 (타깃 EVK 기준)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import struct
import time
from typing import Optional

# 영속화되는 백엔드 상태(서버 재시작 간 위치 유지).
# SDK 서비스 사용자가 읽고 쓸 수 있는 JSON 파일 하나.
_STATE_FILE = "/var/lib/ortho-bender/motor-state.json"

from .motor_backend import MotorBackend
from .tmc260c_driver import (
    SAFETY_CS_MAX, SAFETY_TOFF_MAX,
    CHOPCONF_DEFAULT, SMARTEN_DEFAULT, DRVCONF_DEFAULT, SGCSCONF_DEFAULT,
    DRVCTRL_DEFAULT,
    RESP_S2GA, RESP_S2GB, RESP_OLA, RESP_OLB, RESP_STST,
)

log = logging.getLogger(__name__)

# gpiod 용 i.MX8MP GPIO 칩 매핑
_GPIO_CHIP_MAP = {
    'GPIO3': '/dev/gpiochip2',
    'GPIO5': '/dev/gpiochip4',
}

# SPI ioctl 상수
_SPI_IOC_WR_MODE = 0x40016B01
_SPI_NO_CS = 0x40

# 검증된 동작 타이밍
_RAMP_SUBSLEEP_S = 0.01     # 램프 틱 안의 가드/중단 폴링 주기(공칭)
_RAMP_SUBSLEEP_MIN_S = 0.001  # 하한: 이보다 짧으면 이벤트 루프 오버헤드가 지배

# CS 안정화 시간. 2026-08-31 tools/probe-spi-timing.py 로 실측(초퍼 off,
# 안정 기준 status word 와의 정확 일치 판정): 세 칩 모두 10 us 까지의 모든
# 값에서, SPI 클럭 50 kHz~2 MHz 전 구간 20/20 통과. 예전 500 us 는
# TMC260C 의 CS 셋업 요구(~100 ns)보다 세 자릿수 위였고 3바이트 프레임마다
# 1.5 ms 를 물렸다 — 10프레임 배치가 30바이트 옮기는 데 time.sleep 32 ms.
# 100 us 는 통과한 최소값 대비 10배, 데이터시트 대비 1000배 마진이다.
# 더 낮추려면 프로브를 다시 돌릴 것.
_CS_SETTLE_S = 0.0001      # 100 us (SAI5_RXD1 의 BEND 가 제한 패드)
_DIR_SETUP_S = 0.000010    # 10 us
_INIT_SEQ_CYCLES_FULL = 50      # 풀 초기화 최악 케이스: 칩이 완전 새것일
                                # 때만(서버 기동 후 첫 조그).
_INIT_SEQ_MIN_CYCLES = 5        # 조기 종료가 발동하기 전에 반드시 도는
                                # 최소 풀 초기화 사이클 수.
_INIT_GOOD_CYCLES_EXIT = 3      # 유효한 SPI 응답이 이 횟수 연속되면
                                # 초기화 완료로 선언(칩에 전원이 있고
                                # 응답 중이면 콜드스타트 ~525 ms → ~85 ms).
# enable/silence 레지스터 쓰기의 반복 횟수. 원래 각 5회 — 같은 멱등
# 데이터그램을 다섯 번 보내는 것이었다. probe-spi-timing.py 가 그 중복이
# 의미가 있는지 검사했다: RDSEL 을 01(StallGuard)과 00(마이크로스텝 위치)
# 사이에서 토글하면 응답 포맷으로 DRVCONF 쓰기가 래치됐는지 드러난다 —
# write-only 레지스터 집합이 줄 수 있는 유일한 래치 증거다. 세 칩 모두
# 500 us/50 kHz 에서도 100 us/500 kHz 에서도 첫 프레임에 20/20 래치됐다.
# 2 는 이중 안전으로 남겨둔 값이고(~0.3 ms 비용), 측정상으로는 1 로 충분하다.
_REENABLE_CYCLES = 2            # 이후 조그의 빠른 초퍼 재활성:
                                # CHOPCONF + SGCSCONF 만.
_SILENCE_CYCLES = 2             # 조그 사이 초퍼 off 사이클 수.

# 초소형 이동 정밀 경로의 상한(스텝). 이하의 count 는 램프 기계 대신 바닥
# 주파수 고정 방출로 낸다 — 시간 적분 계수의 ±1 스텝 오차가 미세 이송
# 반복에서 지령을 통째로 삼키는 것을 막는다 (pulse_step 참조). 16 스텝은
# 63.662 steps/unit 의 FEED 기준 0.25 unit — 미세 이송 트래픽 전체를 덮되
# 정상 이동의 램프 성능에는 손대지 않는 크기다.
_EXACT_PULSE_MAX_STEPS = 16


def p_floor(profile: dict | None) -> int:
    """프로파일의 램프 바닥 주파수 (기본 200 Hz — 자기동 영역)."""
    return int((profile or {}).get("start_hz", 200))

# 소프트 스타트 램프: 고정 12스텝/0.36 s 스윕 대신 가속도 제한 방식이다.
# 그래서 속도 변화가 작으면 거의 즉시 목표에 닿고, 200 → 8000 Hz 처럼 크게
# 뛸 때는 약 1 s 에 걸쳐 램프한다. DRVCTRL 1/16 + DEDGE 에서 8000 Hz/s 는
# 1초에 0 → 300 RPM 에 해당한다 — 가속 중에 스톨하는 축이 있으면 벤치에서
# 조정할 것. 여기 값들은 기본값이며, 축별 모션 프로파일
# (services/motion_profiles.py)이 pulse_step(profile=) 으로 덮어쓴다.
# 튜닝 주의: 이 상수는 호출자가 프로파일을 넘기지 않을 때만 쓰이는 폴백이다
# (pulse_step() 직접 호출, 호밍 구간). 운전자용 노브는 축별 모션 프로파일이다
# — 이 상수를 고쳐서 벤치를 튜닝하지 말고 motion_profiles.py /
# PUT /api/motor/profiles/{axis} 를 쓰고, 여기는 프로파일이 없는 호출자를 위한
# 안전한 기본값으로 남겨 둘 것.
_RAMP_ACCEL_HZ_PER_S = 8000
# 램프 해상도: PWM 주파수는 틱마다 한 번만 다시 쓰이므로 속도 곡선은 연속
# 기울기가 아니라 30 ms 계단이다. 이 값을 낮추면 램프가 부드러워지지만, HTTP
# 서버가 도는 같은 이벤트 루프에서 sysfs 쓰기가 늘어난다(측정되는 명령 지연을
# 부풀리는 원인이 바로 이것이다) — 30 ms 는 벤치에서 타협한 값이다. 리밋
# 가드와 제동거리 판정은 틱을 기다리지 않고 그 안에서 10 ms
# (_RAMP_SUBSLEEP_S)마다 폴링한다.
_RAMP_TICK_S = 0.03
_RAMP_DOWN_MAX_S = 1.0     # 감속 램프 최대 시간(정지 반응성 확보)
                           # 무거운 축을 더 부드럽게 세워야 하면 올린다.
                           # 프로파일 decel 이 이보다 느리면 덮어쓰이므로
                           # (pulse_step 의 eff_decel) STOP 은 항상 즉각적이다.

# 벤치 규약: ▶ 버튼(direction=+1)은 모터를 시계방향(전진)으로, ◀ 버튼
# (direction=-1)은 반시계방향으로 돌려야 한다. Veyron 보드의 DIR 입력은
# 우리 모터 장착 기준 DIR=LOW 가 CW, DIR=HIGH 가 CCW 로 배선되어 있어,
# 요청 방향이 양(+)일 때 DIR=LOW 를 구동한다.
_DIR_INVERT = True

# 정적 안전 검증 (tmc260c_driver 에서도 하지만 여기서 이중 확인)
assert (SGCSCONF_DEFAULT & 0x1F) <= SAFETY_CS_MAX, "SGCSCONF CS exceeds safety"
assert (CHOPCONF_DEFAULT & 0xF) <= SAFETY_TOFF_MAX, "CHOPCONF TOFF exceeds safety"


def _ramp_tick_plan(total_s: float) -> tuple[int, float]:
    """`total_s` 짜리 램프를 (틱 수, 틱 길이)로 쪼갠다.

    한 틱보다 짧은 램프는 예전에 _RAMP_TICK_S 하나로 패딩됐다
    (`total_s = max(total_s, _RAMP_TICK_S)`) — 그래서 6 ms 짜리 주파수
    변경도 30 ms 를 물었고, 짧은 이동은 가속·감속에서 그 값을 두 번 낸다.
    270 ms 명령에서 60 ms 는 큰 몫인데 얻는 것은 없다: 램프는 PWM 주파수
    쓰기의 계단이고, 짧은 계단 하나짜리 계단도 여전히 계단이다. 이제 한 틱
    미만이면 더 짧은 단일 틱으로 돈다.

    _ramp 와 _ramp_steps_est 는 이 분할에 반드시 합의해야 한다 — 후자가
    전자의 감속 예약량을 정하므로, 어긋나면 지령 거리를 지나치거나 못 미쳐
    착지하는 이동으로 나타난다.
    """
    if total_s <= 0:
        return 1, 0.0
    n = max(1, -(-int(total_s * 1e6) // int(_RAMP_TICK_S * 1e6)))   # ceil
    return n, total_s / n


def _parse_gpio(pin: str) -> tuple[str, int]:
    """'GPIO5_IO07' -> ('/dev/gpiochip4', 7) 로 파싱한다."""
    parts = pin.split('_IO')
    chip_path = _GPIO_CHIP_MAP.get(parts[0])
    if chip_path is None:
        raise ValueError(f"Unknown GPIO bank: {parts[0]}")
    offset = int(parts[1])
    return chip_path, offset


# 초기화 시퀀스 — 초퍼 활성화에는 쓰기 순서가 중요하다.
# SGCSCONF 는 모듈 기본값으로 적혀 있지만 _init_chip() 이 쓰기 시점에
# PSU 상한이 적용된 값으로 치환한다 (apply_current_cap() 참조).
_INIT_SEQ = [
    ('CHOPCONF', 0x04, CHOPCONF_DEFAULT),
    ('SMARTEN',  0x05, SMARTEN_DEFAULT),
    ('DRVCONF',  0x07, DRVCONF_DEFAULT),
    ('DRVCTRL',  0x00, DRVCTRL_DEFAULT),
    ('SGCSCONF', 0x06, SGCSCONF_DEFAULT),
]


class SpidevMotorBackend(MotorBackend):
    """EVK 테스트 벤치용 Linux spidev + gpiod v2 하드웨어 백엔드.

    SPI_NO_CS 로 3축 수동 CS 토글을 구현. i.MX8MP EVK J21 헤더에 적층한
    Veyron 1×2A 보드들로 동작 검증됨 (2026-05-08).

    cs=0: LIFT, cs=1: BEND, cs=2: FEED.
    """

    is_real_hardware = True

    def __init__(
        self,
        spi_device: str = "/dev/spidev1.0",
        spi_speed_hz: int = 50_000,
        gpio_lift_cs: str = "GPIO5_IO07",
        gpio_bend_cs: str = "GPIO3_IO22",
        gpio_feed_cs: str = "GPIO5_IO13",
        gpio_dir:     str = "GPIO3_IO23",
        pwm_step_path:   str = "/sys/class/pwm/pwmchip2/pwm0",
        pwm_step_export: str = "/sys/class/pwm/pwmchip2/export",
        gpio_limit_lift: str = "",
        gpio_limit_bend: str = "",
        # 구버전 kwargs (받아는 주되 새 이름으로 매핑해 하위 호환 유지)
        gpio_cs1: str | None = None,
        gpio_cs2: str | None = None,
        gpio_feed_step: str | None = None,
        gpio_bend_step: str | None = None,
    ) -> None:
        self._spi_device = spi_device
        self._spi_speed = spi_speed_hz
        self._pwm_path = pwm_step_path
        self._pwm_export = pwm_step_export

        # 논리 이름 -> GPIO 핀 문자열. cs=0/1/2 -> LIFT/BEND/FEED.
        self._gpio_names = {
            'lift_cs': gpio_lift_cs,
            'bend_cs': gpio_bend_cs,
            'feed_cs': gpio_feed_cs,
            'dir':     gpio_dir,
        }
        # 리밋 스위치 입력 (PM-L25, ACTIVE LOW — 분압기가 평시 ~3 V,
        # 스위치가 GND 로 당김). 선택 사항: 빈 핀 문자열 = 미장착.
        self._gpio_inputs: set[str] = set()
        for name, pin in (('limit_lift', gpio_limit_lift),
                          ('limit_bend', gpio_limit_bend)):
            if pin:
                self._gpio_names[name] = pin
                self._gpio_inputs.add(name)
        # cs 인덱스 -> 리밋 입력 이름 (FEED cs=2 는 스위치 없음)
        self._cs_to_limit = {0: 'limit_lift', 1: 'limit_bend'}
        # cs 인덱스 -> 논리 이름
        self._cs_to_name = {0: 'lift_cs', 1: 'bend_cs', 2: 'feed_cs'}

        self._spi = None
        self._gpio_requests: dict[str, object] = {}     # chip_path -> LineRequest
        self._gpio_map: dict[str, tuple[str, int]] = {} # name -> (chip, offset)

        # 축별 위치 추적 (MotorBackend 인터페이스와의 호환)
        self.positions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        self._initialized: dict[int, bool] = {0: False, 1: False, 2: False}

        # 경량 신호 추적 — get_axis_signals() 로 노출되어 Motor Control 의
        # 조그 행이 12V/EN/SG/DIR/STEP LED 를 보여줄 수 있게 한다.
        # `_chip_active` 는 현재 초퍼 상태 (init→True, silence→False)
        # `_chip_responsive` 는 프로브에서 칩이 SPI 에 응답했는지 ("VMot 12 V
        #   살아 있음"의 대용 — 전원이 없으면 SPI 는 0xFF/0x00 을 돌려준다).
        # `_last_sg` 는 cs 별 마지막 관측 StallGuard 비트.
        # `_last_dir` 는 공유 DIR 라인에 마지막으로 구동한 값 (+1/-1).
        # `_pwm_active` 는 PWM4 enable 상태를 반영.
        # `_active_axis` 는 jog/move 태스크가 지금 대상으로 삼는 cs.
        self._chip_active: dict[int, bool] = {0: False, 1: False, 2: False}
        self._chip_responsive: dict[int, bool] = {0: False, 1: False, 2: False}
        self._last_sg: dict[int, bool] = {0: False, 1: False, 2: False}
        # StallGuard 부하의 수치 읽기 (0-1023, RDSEL=01 -> bits 19:10).
        # 위의 불리언은 스톨 '플래그'일 뿐이다. SGT 튜닝에는 수치가 필요하다
        # — 임계값은 실제 절단/벤딩 부하에서 부하 읽기가 어디에 앉는지를
        # 보고 고르는 것이기 때문이다.
        self._last_sg_value: dict[int, int] = {0: 0, 1: 0, 2: 0}
        # cs 별 20비트 응답 전체. 칩들 사이에서 워드 전체를 비교하는 것이
        # 죽은 전원 레일과 진짜 축별 폴트를 구별하는 방법이다.
        self._last_status: dict[int, int] = {}
        self._last_dir: int = 0   # 0 = 미상 / 아직 구동 안 함
        self._pwm_active: bool = False
        # E-STOP kill 래치: 한 번 서면 _pwm_set_hz 가 PWM 을 건드리지 않는다
        # (진행 중이던 램프 틱이 태스크 취소가 도착하기 전까지, E-STOP 이 끈
        # STEP 출력을 ≤30 ms 안에 되켤 수 있기 때문). pulse_step 에서 새 정상
        # 모션이 시작될 때만 풀리며 — 모션 명령 자체가 상류에서 E-STOP 리셋에
        # 게이트된다.
        self._pwm_killed: bool = False
        self._active_axis: Optional[int] = None

        # SPI 버스가 하나 → 모든 전송을 직렬화해서, 동시의 /api/motor/status
        # 읽기가 실행 중인 pulse_step 태스크와 경합하지 않게 한다
        # (경합하면 CS 토글이 깨지고 빈 HTTP 응답이 나온다).
        self._spi_lock = asyncio.Lock()

        # PSU 에서 유도된 전류 스케일 상한 (apply_current_cap 참조). 절대
        # 하드웨어 한계에서 시작하고, main.py 가 활성 PSU 프리셋으로 좁혀서
        # _init_chip 이 전원이 못 먹이는 CS 를 절대 쓰지 않게 한다.
        self._cs_scale_cap: int = SAFETY_CS_MAX

        # 중력 축 유지: hold_axes 에 든 cs 는 유휴 중에도 hold_cs 로 여자
        # 상태를 유지한다 (LIFT 는 여자를 끊으면 가라앉는다). STEP 라인이
        # 공유라 유지 중인 칩은 활성 축과 함께 스텝하므로, 다른 축이 움직이는
        # 동안은 유지를 풀고 끝나면 다시 잡는다. main.py 가 config 에서 채운다.
        self.hold_axes: set[int] = set()
        # cs 별 유지 전류. 어느 축이든 유지될 수 있다 — FEED 와 BEND 도
        # 여자를 끊으면 LIFT 처럼 자유 회전한다. 단지 그걸 티나게 만들
        # 중력 부하가 없을 뿐이다.
        self.hold_cs: int = 8                       # 전 축 공통 기본값
        self.hold_cs_map: dict[int, int] = {}       # cs 별 재정의

        # cs 별 마이크로스텝 분해능(DRVCTRL.MRES 코드, 0=1/256 … 4=1/16).
        # 비어 있으면 전 축이 DRVCTRL_DEFAULT(1/16)를 쓴다. FEED 처럼 분해능이
        # 속도보다 귀한 축만 main.py 가 골라서 올린다 — MRES 를 바꾸면
        # steps_per_unit 도 같은 배율로 바뀌어야 하므로(1/32 는 2배) 짝이
        # 되는 캘리브레이션 기본값과 함께 움직여야 한다. 부팅 시 설정 전용:
        # 런타임에 바꾸려면 재시작(칩 DRVCTRL 은 풀 초기화 때 한 번 쓰인다).
        self.mres_map: dict[int, int] = {}

        # cs 별 StallGuard2 임계값 (SGCSCONF bits 8-14, 부호 있는 7비트).
        # 클수록 '덜' 민감하다. 모듈 기본값이 +63(최대 둔감)이라, 축을
        # 튜닝하기 전에는 SG_RESULT 가 쓸모 있게 움직인 적이 없었다.
        # 위치 상태와 함께 영속화된다.
        self.sgt_map: dict[int, int] = {}

        # 축별 '주행' 코일 전류 (SGCSCONF bits 0-4). 유지 전류는 원래부터
        # 축별이었지만 실제로 움직이는 동안의 전류는 전역 단일값이어서,
        # 토크가 필요한 벤딩 축과 그렇지 않은 피드 롤러가 설정 하나를
        # 나눠 써야 했다. 항상 PSU 상한과 SAFETY_CS_MAX 로 클램프된다.
        self.run_cs_map: dict[int, int] = {}
        self.sg_filter: bool = bool((SGCSCONF_DEFAULT >> 16) & 1)

        # 리밋 가드: 정상 모션 중 리밋 창에 '진입'하는 축을 세운다
        # (에지 트리거; 창 안에서 출발하면 축이 창을 벗어날 때까지 가드는
        # 해제 상태다). PUT /api/motor/protection 으로 토글.
        self.limit_guard: bool = True
        # 가드가 적용되는 축. BEND 의 센서 디스크는 1회전에 슬롯이 여러
        # 개라 에지 트리거 가드는 슬롯마다 축을 세워 버린다 — 그래서
        # main.py 가 LIFT(cs0)로 제한한다.
        self.guard_axes: set[int] = {0, 1, 2}

        # 지령 부호 대비 물리 DIR 라인이 반전된 축. 카운터는 항상 '지령'을
        # 따르므로, 배선을 그대로 두고도 운전자 규약("수직 LIFT 는 + 가
        # 아래")이 끝까지 유지된다.
        self.invert_axes: set[int] = set()

        # 스위치에 대고 호밍된 축 — 위치와 함께 영속화해서, 재시작 후에도
        # 카운터와 "datum 이 실측"이라는 지위가 같이 살아남는다.
        self.homed_persist: set[int] = set()

        # PWM sysfs 쓰기 상태 (_pwm_set_hz 참조): 램프 틱마다
        # duty=0 → enable 재토글하는 것을 피한다 — 그 재토글이 틱마다 STEP
        # 출력의 죽은 주기를 최대 한 개씩 만들었다.
        self._pwm_enabled: bool = False
        self._pwm_last_period_ns: int = 0

        # 지연 위치 영속화 (_save_state_soon 참조).
        self._state_dirty: bool = False
        self._state_save_task = None

    # -------------------------------------------------------------------
    # 영속화 (축 위치가 서버 재시작을 견딘다)
    # -------------------------------------------------------------------
    def _load_state(self) -> None:
        try:
            with open(_STATE_FILE, "r") as f:
                d = json.load(f)
            saved = d.get("positions", {})
            # JSON 키는 문자열 — int 축 ID 로 복원
            for k, v in saved.items():
                try:
                    self.positions[int(k)] = int(v)
                except (TypeError, ValueError):
                    pass
            try:
                self.homed_persist = {int(x) for x in d.get("homed", [])}
            except (TypeError, ValueError):
                self.homed_persist = set()
            try:
                self.sgt_map = {int(k): int(v)
                                for k, v in (d.get("sgt") or {}).items()}
                self.run_cs_map = {
                    int(k): max(0, min(int(v), SAFETY_CS_MAX))
                    for k, v in (d.get("run_cs") or {}).items()}
                self.hold_cs_map = {
                    int(k): max(0, min(int(v), SAFETY_CS_MAX))
                    for k, v in (d.get("hold_cs") or {}).items()}
                if "sg_filter" in d:
                    self.sg_filter = bool(d["sg_filter"])
            except (TypeError, ValueError):
                self.sgt_map = {}
            log.info("Restored motor positions from %s: %s (homed=%s)",
                     _STATE_FILE, self.positions, sorted(self.homed_persist))
        except FileNotFoundError:
            log.info("No saved motor state at %s — starting from zero", _STATE_FILE)
        except Exception as exc:
            log.warning("Failed to load motor state (%s) — starting from zero", exc)

    def _state_snapshot(self) -> dict:
        """영속 상태의 직렬화 가능한 사본 — 이벤트 루프 '위에서' 뜬다.

        쓰기는 워커 스레드에서 일어나는데, 모션 코루틴이 아직 고치고 있는
        dict 를 json.dump 가 순회하면 "dictionary changed size during
        iteration" 이 난다. 스레드 경계를 넘는 것은 이 사본뿐이고, 사본은
        다른 무엇도 돌 수 없는 곳에서 만들어진다.
        """
        return {
            "positions": {str(k): int(v) for k, v in self.positions.items()},
            "homed": sorted(self.homed_persist),
            "sgt": {str(k): int(v) for k, v in self.sgt_map.items()},
            "run_cs": {str(k): int(v) for k, v in self.run_cs_map.items()},
            # 유지 토크는 축별로 설정되면서도 기록된 적이 없어서 재시작마다
            # 조용히 되돌아갔다 -- 중력 축에서는 그 유실이 '주차됨'과
            # '미끄러짐'의 차이다.
            "hold_cs": {str(k): int(v) for k, v in self.hold_cs_map.items()},
            "sg_filter": bool(self.sg_filter),
        }

    def _write_state(self, data: dict) -> None:
        """스냅샷의 블로킹 쓰기. 보드 eMMC 실측 0.87 ms 통상 / 1.6 ms
        최악 — 작지만, 매 이동 끝마다 이벤트 루프 위에서 지불되고 있었고
        그러면 비행 중인 다른 모든 요청의 지연에도 얹힌다."""
        try:
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
            tmp = _STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, _STATE_FILE)
        except Exception as exc:
            log.debug("Save motor state failed: %s", exc)

    def _save_state(self) -> None:
        """동기 저장. 기동·종료 등 콜드 패스용 — 모션 핫패스는
        _save_state_soon() 을 쓴다."""
        self._write_state(self._state_snapshot())

    def _save_state_soon(self) -> None:
        """이벤트 루프를 막지 않고 영속화한다.

        큐잉이 아니라 병합(coalescing)이다: 그 일을 하는 것은 _state_dirty
        플래그다 — 배출 루프가 매 쓰기 전에 플래그를 지우므로, 쓰기가 비행
        중일 때 도착한 호출자들은 그 쓰기에 흡수되고, 짧은 조그 연타는
        조그마다 한 번이 아니라 마지막에 한 번 더 파일을 쓴다. 아래의 비행 중
        태스크 확인은 그 안전성의 근거가 아니고(두 번째 태스크는 플래그가
        지워진 것을 보고 종료한다) 조그마다 태스크 객체를 만드는 것을 피할
        뿐이다. 도는 루프가 없으면(테스트, 동기 호출자) 동기 저장으로
        폴백한다.
        """
        self._state_dirty = True
        task = self._state_save_task
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._save_state()
            return
        try:
            self._state_save_task = loop.create_task(self._save_state_loop())
        except RuntimeError:          # loop closing — persist here instead
            self._save_state()

    async def _save_state_loop(self) -> None:
        while self._state_dirty:
            self._state_dirty = False
            data = self._state_snapshot()
            try:
                await asyncio.to_thread(self._write_state, data)
            except Exception as exc:
                log.debug("Deferred motor state save failed: %s", exc)

    # -------------------------------------------------------------------
    # 라이프사이클
    # -------------------------------------------------------------------
    async def open(self) -> None:
        """SPI 디바이스 열기, GPIO 라인 요청, SPI_NO_CS 모드 설정.

        순서가 결정적이다: spi-imx 상태를 리셋하려면 SPI 를 GPIO 요청보다
        *먼저* 열어야 한다 (아니면 다음 재부팅부터 EBUSY).
        """
        # 1. SPI 먼저 (spi-imx 상태를 리셋해야 GPIO 요청이 깨끗하다)
        try:
            import spidev
        except ImportError:
            log.error("spidev module not available — install python3-spidev")
            raise

        bus, dev = self._parse_spidev_path(self._spi_device)
        spi = spidev.SpiDev()
        spi.open(bus, dev)
        spi.max_speed_hz = self._spi_speed
        spi.bits_per_word = 8
        try:
            spi.mode = 3
        except OSError:
            # i.MX8MP DTS 가 cs-gpios 에서 CS_HIGH 극성을 잡아둘 수 있다
            spi.mode = 3 | 0x04
            log.warning("SPI mode 3 failed, set mode 0x7 (mode 3 + CS_HIGH)")

        # SPI_NO_CS: spi-imx 가 네이티브 CS 나 cs-gpios 를 토글하지 못하게
        # 한다. 칩 선택은 spi_transfer() 의 수동 CS 토글이 담당한다.
        try:
            fcntl.ioctl(
                spi.fileno(),
                _SPI_IOC_WR_MODE,
                struct.pack('B', 3 | _SPI_NO_CS),
            )
        except OSError as exc:
            log.warning("SPI_NO_CS ioctl failed (%s) — manual toggle still attempted", exc)

        # spi-imx 상태를 가라앉히기 위한 더미 전송
        spi.xfer2([0, 0, 0])
        await asyncio.sleep(0.05)
        self._spi = spi
        log.info("SPI opened: %s @ %d Hz, mode 3 + NO_CS", self._spi_device, self._spi_speed)
        # 디스크에서 마지막 위치를 복원
        self._load_state()

        # 2. GPIO 요청 (gpiod v2)
        try:
            import gpiod
            from gpiod.line import Direction, Value
        except ImportError:
            log.error("gpiod >= 2.0 not available — install python3-gpiod")
            raise

        # GPIO 라인을 칩별로 묶는다
        chip_lines: dict[str, dict[str, int]] = {}
        for name, gpio_str in self._gpio_names.items():
            chip_path, offset = _parse_gpio(gpio_str)
            self._gpio_map[name] = (chip_path, offset)
            chip_lines.setdefault(chip_path, {})[name] = offset

        for chip_path, lines in chip_lines.items():
            line_cfg = {}
            for name, offset in lines.items():
                if name in self._gpio_inputs:
                    # 리밋 스위치: 입력, 바이어스 없음 — 레벨은 외부 분압기
                    # (~500 Ω 테브냉)가 정한다.
                    line_cfg[offset] = gpiod.LineSettings(
                        direction=Direction.INPUT,
                    )
                else:
                    # CS 라인은 평시 HIGH, DIR 은 평시 LOW
                    init_value = Value.ACTIVE if name.endswith('_cs') else Value.INACTIVE
                    line_cfg[offset] = gpiod.LineSettings(
                        direction=Direction.OUTPUT,
                        output_value=init_value,
                    )
            req = gpiod.request_lines(
                chip_path,
                consumer="ortho-bender-spi",
                config=line_cfg,
            )
            self._gpio_requests[chip_path] = req
            log.info("GPIO chip %s: requested %s", chip_path, lines)

    async def close(self) -> None:
        """SPI, GPIO, PWM 자원을 해제한다."""
        # 마지막 위치를 영속화
        self._save_state()
        # PWM 정지 (아직 돌고 있을 경우 대비)
        try:
            with open(f"{self._pwm_path}/enable", 'w') as f:
                f.write('0\n')
        except Exception:
            pass

        # 닫기 전에 모든 칩을 침묵시킨다
        for cs in (0, 1, 2):
            try:
                await self._silence_chip(cs)
            except Exception:
                pass

        if self._spi:
            try:
                self._spi.close()
            except Exception:
                pass
        for req in self._gpio_requests.values():
            try:
                req.release()
            except Exception:
                pass

    @staticmethod
    def _parse_spidev_path(path: str) -> tuple[int, int]:
        name = path.split('spidev')[1]
        parts = name.split('.')
        return int(parts[0]), int(parts[1])

    # -------------------------------------------------------------------
    # GPIO 헬퍼
    # -------------------------------------------------------------------
    def _set_dir(self, axis: int, direction: int) -> None:
        """`axis` 에 대해 공유 DIR 라인을 구동한다. 축별 반전
        (invert_axes)을 존중한다."""
        phys = -direction if axis in self.invert_axes else direction
        self._gpio_set('dir', (phys > 0) != _DIR_INVERT)

    def _gpio_set(self, name: str, high: bool) -> None:
        from gpiod.line import Value
        chip_path, offset = self._gpio_map[name]
        self._gpio_requests[chip_path].set_value(
            offset, Value.ACTIVE if high else Value.INACTIVE
        )
        # LED 행을 위한 DIR 추적. 실제 논리 방향은 원시 핀 값에 _DIR_INVERT
        # 를 XOR 한 것 — 라인을 구동하기 전에 같은 XOR 를 적용하는
        # pulse_step() 참조.
        if name == 'dir':
            logical_pos = (high != _DIR_INVERT)
            self._last_dir = +1 if logical_pos else -1

    def _gpio_get(self, name: str) -> bool:
        from gpiod.line import Value
        chip_path, offset = self._gpio_map[name]
        return self._gpio_requests[chip_path].get_value(offset) == Value.ACTIVE

    # -------------------------------------------------------------------
    # MotorBackend 인터페이스
    # -------------------------------------------------------------------
    async def spi_transfer(self, cs: int, data: bytes) -> bytes:
        """수동 CS 토글을 쓰는 SPI 전송 (_CS_SETTLE_S 안정화).

        cs=0 → LIFT, cs=1 → BEND, cs=2 → FEED.
        self._spi_lock 으로 직렬화되므로 동시 호출자(예: pulse_step 실행 중의
        status 읽기)가 CS 프레이밍을 깨지 못한다.
        """
        if self._spi is None:
            raise RuntimeError("SPI not opened — call open() first")

        cs_name = self._cs_to_name.get(cs)
        if cs_name is None:
            raise ValueError(f"cs={cs} out of range (0=LIFT, 1=BEND, 2=FEED)")

        def _xfer_blocking() -> bytes:
            self._gpio_set(cs_name, False)              # CS 는 active LOW
            time.sleep(_CS_SETTLE_S)
            rx = self._spi.xfer2(list(data))
            time.sleep(_CS_SETTLE_S)
            self._gpio_set(cs_name, True)               # CS 는 평시 HIGH
            time.sleep(_CS_SETTLE_S)
            return bytes(rx)

        async with self._spi_lock:
            return await asyncio.to_thread(_xfer_blocking)

    async def spi_transfer_batch(self, cs: int, frames: list[bytes]) -> list[bytes]:
        """한 번의 스레드 홉 안에서 한 칩에 데이터그램 여러 개를 보낸다.

        프레임마다 spi_transfer() 를 부르는 것과 와이어 위에서는 바이트
        단위로 동일하다: 같은 CS 토글, 같은 안정화 시간, 같은 순서. 없애는
        것은 프레임 사이의 이벤트 루프 왕복인데, 이것이 SPI 트래픽 자체보다
        크게 측정됐다 -- 10 프레임이면 버스 시간 약 20 ms 여야 하는 것이
        60-90 ms 씩 들었고, 그 오버헤드가 다른 축이 움직이는 동안 LIFT 를
        0.44 s 나 무여자로 두는 원인이다.
        """
        if self._spi is None:
            raise RuntimeError("SPI not opened — call open() first")

        cs_name = self._cs_to_name.get(cs)
        if cs_name is None:
            raise ValueError(f"cs={cs} out of range (0=LIFT, 1=BEND, 2=FEED)")

        def _xfer_all() -> list[bytes]:
            out: list[bytes] = []
            for data in frames:
                self._gpio_set(cs_name, False)          # CS 는 active LOW
                time.sleep(_CS_SETTLE_S)
                rx = self._spi.xfer2(list(data))
                time.sleep(_CS_SETTLE_S)
                self._gpio_set(cs_name, True)           # CS 는 평시 HIGH
                time.sleep(_CS_SETTLE_S)
                out.append(bytes(rx))
            return out

        async with self._spi_lock:
            return await asyncio.to_thread(_xfer_all)

    async def set_gpio(self, pin: str, value: bool) -> None:
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_map:
                self._gpio_set(name, value)
                return
        log.warning("GPIO %s not in configured pins", pin)

    async def get_gpio(self, pin: str) -> bool:
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_map:
                return self._gpio_get(name)
        return False

    async def pulse_step_multi(
        self,
        axes: list[int],
        count: int,
        freq_hz: int,
        direction: int,
    ) -> None:
        """여러 축에 동시에 STEP 펄스를 낸다.

        나열된 모든 축을 초기화한 뒤 같은 PWM4 STEP 신호(병렬 배선)로
        구동한다. 3축 동시는 보수적으로 간다: PSU 과도 안전을 위해 hz 를
        4000 으로 클램프하고 3 s 느린 램프를 쓴다.

        어느 축에서든 폴트가 나면 전 축을 즉시 중단한다.
        """
        if not axes:
            return
        for a in axes:
            if a not in (0, 1, 2):
                raise ValueError(f"axis {a} out of range (0/1/2)")
        # 3축 안전: hz 상한
        if len(axes) >= 2 and freq_hz > 4000:
            freq_hz = 4000
        if freq_hz < 200:
            freq_hz = 200
        count = max(1, min(count, 1_000_000))
        duration_s = count / freq_hz
        if duration_s > 30.0:
            duration_s = 30.0
            count = int(duration_s * freq_hz)

        self._pwm_killed = False   # 새 모션 — E-STOP kill 래치 해제
        # 공유 STEP: 참여하지 않는 유지 축은 먼저 풀어야 한다.
        for h in self.hold_axes - set(axes):
            if self._chip_active.get(h):
                await self._silence_chip(h)
        self._set_dir(axes[0], direction)
        await asyncio.sleep(_DIR_SETUP_S)

        # 각 축을 순차 초기화
        for a in axes:
            await self._init_chip(a)
            status = await self._read_status(a)
            if self._has_fault(status):
                log.error("axis %d fault before run: 0x%05X — aborting", a, status)
                for ax in axes:
                    await self._silence_chip(ax)
                raise RuntimeError(f"axis {a} fault (0x{status:05X})")

        await self._pwm_ensure_exported()

        # 축별 폴트 감시를 곁들인 3 s 느린 램프
        ramp_steps = 30
        ramp_sec = 3.0
        try:
            for i in range(ramp_steps):
                h = int(200 + (freq_hz - 200) * i / (ramp_steps - 1))
                await self._pwm_set_hz(h)
                for a in axes:
                    status = await self._read_status(a)
                    if self._has_fault(status):
                        log.error("axis %d fault during ramp: 0x%05X", a, status)
                        return  # finally 블록이 침묵 + PWM 비활성 처리
                await asyncio.sleep(ramp_sec / ramp_steps)

            # 유지 + 감시
            t0 = time.monotonic()
            while time.monotonic() - t0 < duration_s:
                await asyncio.sleep(0.1)
                for a in axes:
                    status = await self._read_status(a)
                    if self._has_fault(status):
                        log.error("axis %d fault during run: 0x%05X", a, status)
                        return
        finally:
            await self._pwm_disable()
            for a in axes:
                if a in self.hold_axes and not self._pwm_killed:
                    await self._hold_chip(a)
                else:
                    await self._silence_chip(a)
            if not self._pwm_killed:
                for h in self.hold_axes - set(axes):
                    try:
                        await self._hold_chip(h)
                    except Exception as exc:
                        log.warning("re-hold cs=%d failed: %s", h, exc)

        for a in axes:
            self.positions[a] = self.positions.get(a, 0) + (count * direction)

    async def pulse_step(
        self, axis: int, count: int, freq_hz: int, direction: int,
        profile: dict | None = None,
    ) -> None:
        """`axis` 에 `freq_hz` 로 STEP 펄스 `count` 개를 낸다.

        구현: PWM4(pwmchip2/pwm0)가 3개 칩 모두에 병렬 STEP 신호를 낸다.
        대상 축만 초기화하고 나머지는 침묵 상태로 두므로, 대상 모터만 돈다.

        안전:
          - CS 는 한계 안에 유지 (CHOPCONF/SGCSCONF 기본값은 검증됨)
          - 폴트 플래그(OT/S2G/OL)는 즉시 중단
          - hz 는 [200, 8000], count 는 [1, 1_000_000] 로 클램프
        """
        if axis not in (0, 1, 2):
            raise ValueError(f"axis={axis} out of range (0=LIFT, 1=BEND, 2=FEED)")
        if freq_hz < 200:
            freq_hz = 200
        if freq_hz > 8000:
            freq_hz = 8000
        count = max(1, min(count, 1_000_000))
        duration_s = count / freq_hz
        if duration_s > 30.0:
            log.warning("pulse_step duration %.1fs clamped to 30s", duration_s)
            duration_s = 30.0
            count = int(duration_s * freq_hz)

        # 시작 위치 스냅샷 — finally 는 항상 여기 값에 닿는다.
        pos_before = self.positions.get(axis, 0)
        # t0 는 PWM 이 실제로 램프를 시작할 때까지 None → finally 가 안전.
        t0: float | None = None
        elapsed = 0.0

        try:
            # init/PWM 셋업 전부를 try '안에' 둔다 — 초기화 중 취소돼도
            # finally 블록(침묵 + 위치 스냅샷)이 돌게 하기 위해서다. 이걸로
            # 750 ms 초기화 구간이 취소 가능해진다.
            self._pwm_killed = False   # 새 모션 — E-STOP kill 래치 해제
            self._active_axis = axis
            await self._yield_held(axis)   # 공유 STEP: 유지 축을 풀어준다
            self._set_dir(axis, direction)
            await asyncio.sleep(_DIR_SETUP_S)
            # 구동 전 폴트 확인. status 는 init 배치 자체에서 돌아온다 —
            # 같은 프레임, 시퀀스의 같은 자리(초퍼가 켜진 뒤)이고 SPI 왕복이
            # 한 번 줄어든다.
            status = await self._init_chip(axis)
            if self._has_fault(status):
                log.error("axis %d fault before run: 0x%05X — aborting", axis, status)
                raise RuntimeError(f"axis {axis} fault detected (0x{status:05X})")

            if count <= _EXACT_PULSE_MAX_STEPS:
                # ---- 초소형 이동 정밀 경로 ---------------------------------
                # 램프·순항·트림 기계를 통째로 건너뛰고, 정확히 count 스텝을
                # 바닥 주파수로 낸다 — 호밍 _home_move 와 같은 방식이다(그쪽
                # 주석대로 자기동 영역이라 램프가 필요 없고, 정지는 폴 주기
                # 단위로 스텝 정확하다). 램프 기계는 시간 적분으로 스텝을
                # 계수하므로 초소형 이동에서 ±1 스텝을 흘리는데, 그 1 스텝이
                # 카운터를 목표보다 앞세우면 다음 미세 지령의 갭이 1 스텝
                # 밑으로 떨어져 통째로 무시된다 — "20회 지령이면 20회 모두
                # 움직여야 한다"는 요구가 깨지는 유일한 경로였다. 여기서는
                # 카운터가 정확히 count 만큼만 전진하므로, 절대 그리드 반복에서
                # 온전한 스텝이 있는 지령은 반드시 움직인다.
                floor_hz = min(int(p_floor(profile)), freq_hz)
                await self._pwm_ensure_exported()
                guarded = self.limit_guard and axis in self.guard_axes
                armed = guarded and self.limit_active(axis) is False
                emitted = 0
                t0 = time.monotonic()
                await self._pwm_set_hz(floor_hz)
                try:
                    while emitted < count:
                        left = count - emitted
                        await asyncio.sleep(max(_RAMP_SUBSLEEP_MIN_S,
                                                min(0.005, left / floor_hz)))
                        if self._pwm_killed:      # E-STOP — 계수 즉시 동결
                            break
                        emitted = min(int((time.monotonic() - t0) * floor_hz),
                                      count)
                        self.positions[axis] = pos_before + emitted * direction
                        if guarded:
                            lim = self.limit_active(axis)
                            if lim is False:
                                armed = True
                            elif lim and armed:
                                log.warning("axis %d limit tripped in micro "
                                            "move — stopping", axis)
                                break
                finally:
                    await self._pwm_disable()
                    self.positions[axis] = pos_before + emitted * direction
                return

            # PWM4 셋업 — 여기서부터 STEP 신호가 살아난다.
            # 가속도 제한 소프트 스타트(축별 모션 프로파일: 시작 바닥값,
            # 가속률, linear/S-curve 형상). 속도 변화가 작으면 ~한 틱에 목표에
            # 닿고, 크게 뛰면 설정된 가속도로 램프한다.
            p = profile or {}
            start_hz = int(p.get("start_hz", 200))
            accel = float(p.get("accel_hz_s", _RAMP_ACCEL_HZ_PER_S))
            decel = float(p.get("decel_hz_s", _RAMP_ACCEL_HZ_PER_S))
            shape = p.get("shape", "linear")
            await self._pwm_ensure_exported()
            h = min(start_hz, freq_hz)
            floor_hz = h
            # 짧은 이동 피크 캡: 가속+감속만으로 지령 스텝 수를 넘지 못하게
            # 순항 주파수를 제한한다(삼각 프로파일). 이것이 없으면 0.2 유닛
            # 톡 치기가 풀스피드까지 램프해 두 램프가 이동을 ~2-3배
            # 지나친다.
            if accel > 0 and decel > 0:
                denom = 1.0 / (2.0 * accel) + 1.0 / (2.0 * decel)
                f_reach = int((floor_hz * floor_hz + count / denom) ** 0.5)
                if f_reach < freq_hz:
                    freq_hz = max(floor_hz, f_reach)
            span = max(0, freq_hz - floor_hz)
            # 감속률: 프로파일을 존중하되 _RAMP_DOWN_MAX_S 보다 오래 끌지는
            # 않는다 — 정지는 항상 즉각적으로 느껴져야 한다.
            eff_decel = max(decel, span / _RAMP_DOWN_MAX_S) if span else decel
            # 리밋 스위치 가드(에지 트리거, 축이 창 밖에 있을 때만 장전):
            # 램프(10 ms 서브 폴링)와 순항 감시가 공유한다. 빠른 축은 ~0.7 u
            # 창을 수십 ms 에 가로지른다 — 예전의 100 ms 단독 검사는 눈치도
            # 못 채고 그대로 통과할 수 있었다.
            guarded = self.limit_guard and axis in self.guard_axes
            guard = {"armed": guarded and self.limit_active(axis) is False,
                     "hit": False}

            def guard_check() -> bool:
                if not guarded or guard["hit"]:
                    return guard["hit"]
                lim = self.limit_active(axis)
                if lim is False:
                    guard["armed"] = True
                elif lim and guard["armed"]:
                    guard["hit"] = True
                return guard["hit"]

            # ---- 제동거리 제어 ------------------------------------------
            # 이동은 감속을 지령 거리 '안에' 포함해야 한다: "45 deg" 는 45 에서
            # 멈춰야지 45 를 지나며 감속하면 안 된다. 램프를 미리 예산하는
            # 방식은 통하지 않았다 — 실제 소요(10 ms 가드 슬라이스, sysfs
            # 쓰기, 스케줄러 지터)가 이상적 일정과 다르기 때문이다. 대신 가속·
            # 순항 구간을 '현재' 주파수 기준의 실시간 제동거리가 남은 거리에
            # 닿을 때까지 돌리고, 그때 감속을 시작한다. 예약분은 매 정지를
            # 살짝 짧게 치우치게 한다 — 스텝은 무를 수 없다 — 그리고 마지막
            # 트림 패스가 남은 간격을 정확히 메운다.
            def brake_now() -> bool:
                if eff_decel <= 0:
                    return False
                cur = floor_hz
                if self._pwm_last_period_ns:
                    cur = int(1e9 / self._pwm_last_period_ns)
                cur = max(floor_hz, min(freq_hz, cur))
                d_span = max(0, cur - floor_hz)
                if d_span <= 0:
                    return False
                d_t = (1.5 if shape == "scurve" else 1.0) * d_span / eff_decel
                # 15 % 예약: 감속 램프는 목표 '앞에서' 끝나야 느린 트림
                # 패스가 최종 접근을 할 수 있다 — 과주행은 복구 불가,
                # 미달은 쉽게 고쳐진다.
                need = int(1.15 * self._ramp_steps_est(
                    cur, floor_hz, d_t, shape))
                done = abs(self.positions.get(axis, 0) - pos_before)
                return done + need >= count

            await self._pwm_set_hz(h)
            # 실시간 스텝 계수를 곁들인 램프업: 램프 중에 나간 모든 스텝이
            # 위치 표시와 지령 거리 양쪽에 계산된다(짧은 조그는 램프 안에서
            # 통째로 끝날 수 있다 — 예전에는 보이지도 않았고 ~2배
            # 과주행했다).
            ramp_up = await self._ramp(h, freq_hz, accel, shape,
                                       track=(axis, direction),
                                       guard_cb=guard_check,
                                       abort_cb=brake_now)
            pos_mid = self.positions.get(axis, 0)
            # 순항 상한: 최고 주파수 기준으로 남은 거리 + 여유 — 순항을
            # 실제로 끝내는 것은 brake_now() 다.
            remaining = max(0, count - abs(pos_mid - pos_before))
            duration_s = (remaining / freq_hz) + 0.5 if not guard["hit"] else 0.0
            t0 = time.monotonic()

            # 순항 + 감시: 리밋 가드와 위치는 10 ms 주기(빠른 축은 센서
            # 창을 수십 ms 에 가로지른다), SPI 폴트/스톨 읽기는 100 ms.
            stall_since: float | None = None
            STALL_TIMEOUT_S = 0.6
            clean_end = True
            next_status_t = 0.0
            try:
                while time.monotonic() - t0 < duration_s:
                    await asyncio.sleep(0.01)
                    elapsed = time.monotonic() - t0
                    steps_so_far = min(int(elapsed * freq_hz), remaining)
                    self.positions[axis] = pos_mid + (steps_so_far * direction)

                    if brake_now():
                        break   # 지금 감속을 시작하면 목표에 착지한다
                    if guard_check():
                        log.warning("axis %d limit switch tripped mid-motion "
                                    "— stopping (limit guard)", axis)
                        break   # clean_end 는 True 유지 → 감속 정지
                    if elapsed < next_status_t:
                        continue
                    next_status_t = elapsed + 0.1
                    status = await self._read_status(axis)
                    if self._has_fault(status):
                        log.error("axis %d fault during run: 0x%05X — aborting", axis, status)
                        clean_end = False   # 폴트는 감속 없이 즉시 정지
                        break
                    if self._is_stall(status):
                        if stall_since is None:
                            stall_since = time.monotonic()
                            log.warning("axis %d stall (SG=1) — monitoring", axis)
                        elif time.monotonic() - stall_since >= STALL_TIMEOUT_S:
                            log.error("axis %d persistent stall (>%.1fs) — aborting",
                                      axis, STALL_TIMEOUT_S)
                            clean_end = False
                            break
                    else:
                        stall_since = None
                else:
                    # brake_now() 없이 순항 상한에 닿음(아주 짧거나 스팬 0
                    # 이동): 지령 거리로 정산한다.
                    self.positions[axis] = pos_before + (count * direction)
            except asyncio.CancelledError:
                # 정상 정지(jog_stop / 태스크 취소): finally 블록이 초퍼를
                # 침묵시키기 전에 감속한다 — 단, E-STOP 이 이미 PWM 을 죽였다면
                # (self._pwm_active False) 모터는 전기적으로 멈춘 상태이고
                # 여기서의 램프는 안전 경로만 늦춘다.
                # 감속 램프가 계수를 넘겨받기 전에, 마지막 100 ms 틱 이후
                # 나간 순항 스텝을 먼저 정산한다.
                elapsed = time.monotonic() - t0
                self.positions[axis] = pos_mid + (
                    min(int(elapsed * freq_hz), remaining) * direction)
                if self._pwm_active:
                    try:
                        await self._ramp(freq_hz, floor_hz, eff_decel, shape,
                                         track=(axis, direction))
                    except Exception:
                        pass
                raise
            # 제어된 정지(자연 종료): 바닥값까지 감속해서 고속 조그가 0 으로
            # 꽝 떨어지지 않게 한다(1/16 마이크로스텝 속도에서 스텝 유실/공진
            # 위험). 단, **리밋 가드 발동은 예외 — 즉시 정지한다**: 감속
            # 램프는 최악 _RAMP_DOWN_MAX_S(1 s)를 끌며 그동안 축이 리밋 창을
            # 지나 기구 한계로 계속 진행한다. 리밋을 밟은 시점에는 위치
            # 충실도(감속으로 지키는 것)보다 더 못 가게 하는 것이 우선이고,
            # 어차피 datum 은 스위치에 대고 다시 잡는다. finally 가 바로
            # _pwm_disable 로 STEP 을 끊는다.
            if clean_end and not guard["hit"] and self._pwm_active:
                cur_hz = freq_hz
                if self._pwm_last_period_ns:
                    cur_hz = min(freq_hz, max(floor_hz,
                                 int(1e9 / self._pwm_last_period_ns)))
                await self._ramp(cur_hz, floor_hz, eff_decel, shape,
                                 track=(axis, direction),
                                 abort_cb=lambda: abs(
                                     self.positions.get(axis, 0) - pos_before
                                 ) >= count,
                                 remaining_cb=lambda: count - abs(
                                     self.positions.get(axis, 0) - pos_before))

                # ---- 트림: 지령 거리에 정확히 착지 ----
                # 가속+순항+감속을 예산해도 램프 타이밍은 스텝 단위로 정확할
                # 수 없다. 아직 모자란 만큼을 램프 바닥 주파수로 내보낸다
                # (느리고, 바닥값은 모터의 자기동 영역 안이라 램프도 필요
                # 없다).
                if not guard["hit"]:
                    done = abs(self.positions.get(axis, 0) - pos_before)
                    short = count - done
                    if 0 < short <= count:
                        trim_s = min(short / float(floor_hz), 1.5)
                        base_pos = self.positions.get(axis, 0)
                        t_trim = time.monotonic()
                        await self._pwm_set_hz(floor_hz)
                        try:
                            while True:
                                left = short - min(
                                    int((time.monotonic() - t_trim) * floor_hz),
                                    short)
                                await asyncio.sleep(max(
                                    _RAMP_SUBSLEEP_MIN_S,
                                    min(0.005, left / float(floor_hz))))
                                el = time.monotonic() - t_trim
                                emitted = min(int(el * floor_hz), short)
                                self.positions[axis] = base_pos + emitted * direction
                                if el >= trim_s or emitted >= short:
                                    break
                                if guard_check():
                                    break
                        finally:
                            self.positions[axis] = base_pos + min(
                                int((time.monotonic() - t_trim) * floor_hz),
                                short) * direction
                        log.debug("axis %d trim: %d steps at %d Hz",
                                  axis, short, floor_hz)
        finally:
            # 어떤 경로로 나가든(성공, 취소, 폴트, 초기화 중 예외) 모터를
            # 안전하게 만든다: 중력 축은 저전류 유지로, 나머지는 침묵으로,
            # 풀어줬던 축은 다시 유지로(E-STOP 후에는 전부 생략).
            try:
                await self._pwm_disable()
            except Exception:
                pass
            await self._finish_axis(axis)
            # 위치는 전 구간(램프업 적분, 순항 틱, 감속 적분)에서 실시간으로
            # 유지된다 — 종료 시 재계산은 없다. 그 재계산이 짧은 조그가 램프
            # 안에서 한 일을 전부 지워 버리곤 했다. pos_before/t0 는 로그
            # 맥락용으로만 남는다.
            _ = pos_before, t0
            # 갱신된 위치를 영속화 — 서버가 재시작해도 여기서 이어간다
            self._save_state_soon()
            # 이 jog/move 가 끝나면 active_axis 를 지운다 — STEP LED 는
            # 모션이 비행 중인 동안만 축을 강조해야 한다.
            if self._active_axis == axis:
                self._active_axis = None

    # -------------------------------------------------------------------
    # 신호 헬퍼 (대시보드의 LED 행)
    # -------------------------------------------------------------------
    async def clear_driver_faults(self) -> dict:
        """전원을 끊지 않고 래치된 드라이버 폴트를 해제한다.

        TMC26x 의 지락(short-to-ground) 검출은 래치된다: 비교기가 한 번
        발화하면 드라이버를 껐다 켤 때까지 플래그가 남아, 재초기화를 견디고
        이후의 모든 이동이 거부된다. 지금까지 벗어나는 길은 물리적 전원
        재투입뿐이었다 — /api/motor/{enable,disable} 은 IPC 메시지를 M7 로
        보낼 뿐 벤치 칩에는 전혀 닿지 않기 때문이다.

        순서는: 전 칩 초퍼 off → 출력이 실제로 스위칭을 멈출 만큼 대기 →
        유지가 걸려야 하는 축만 재초기화. 셋을 전부 재초기화하면 벤치 전체가
        초퍼 ON 이 되고, 다음 조그가 공유 STEP 라인으로 모든 모터를 몰아
        버린다(2026-05-09 사건).
        """
        before = dict(self._last_status)
        for cs in (0, 1, 2):
            try:
                await self._silence_chip(cs)
            except Exception as exc:
                log.warning("fault clear: silence cs=%d failed: %s", cs, exc)

        await asyncio.sleep(0.3)   # 출력이 정말로 스위칭을 멈춰야 한다

        cleared, still = [], []
        for cs in (0, 1, 2):
            try:
                await self._init_chip(cs)
                status = await self._read_status(cs)
                (still if self._has_fault(status) else cleared).append(cs)
                if cs in self.hold_axes:
                    await self._hold_chip(cs)
                else:
                    await self._silence_chip(cs)
            except Exception as exc:
                log.warning("fault clear: probe cs=%d failed: %s", cs, exc)
                still.append(cs)

        log.info("driver fault clear: cleared=%s still_faulted=%s", cleared, still)
        return {
            "cleared": cleared,
            "still_faulted": still,
            "before": {str(k): f"0x{v:05X}" for k, v in before.items()},
            "after": {str(k): f"0x{v:05X}"
                      for k, v in self._last_status.items()},
        }

    def rail_suspect(self) -> bool:
        """축들이 각자 고장난 것이 아니라 모터 전원 레일이 죽은 것으로
        보일 때 True.

        독립된 드라이버 보드 셋이 VMot 레일 하나를 공유한다. 그 레일이
        내려가도 로직은 VCC_IO 로 돌아 SPI 응답은 계속하지만 출력단은 꺼져
        있어, 지락 검출 비교기들이 전부 같은 폴트를 보고하고 정지(standstill)
        플래그는 서지 않는다. 그러므로 standstill 없는 비트 단위 동일 폴트
        워드 셋은 레일 증상이지 우연히 겹친 지락 셋이 아니다 -- 이걸 말해
        주는 것만으로 몇 시간짜리 추적이 전압 측정 한 번으로 줄어든다.
        """
        words = [w for w in self._last_status.values() if w is not None]
        if len(words) < 2 or len(set(words)) != 1:
            return False
        word = words[0]
        faulted = bool(word & (RESP_S2GA | RESP_S2GB | RESP_OLA | RESP_OLB))
        standstill = bool(word & RESP_STST)
        return faulted and not standstill

    def get_axis_signals(self, cs: int) -> dict:
        """한 cs 의 LED 신호 다섯 개 스냅샷을 돌려준다.

        - vmot:  칩이 최근 SPI 에 응답함 → VMot 12 V 살아 있음(추정).
        - en:    이 cs 의 초퍼가 현재 ON (초기화 완료, 침묵 아님).
        - sg:    이 cs 의 마지막 DRV_STATUS 읽기의 StallGuard 비트.
                 주의: 침묵 중(코일 전류 0)에는 StallGuard 가 무전류를 스톨로
                 해석해 SG 가 1 로 읽힌다. 프론트는 `en` 을 봐서 가릴 수 있다.
        - dir:   +1 / -1 — 공유 DIR 라인에 마지막으로 구동한 논리 방향.
                 0 은 "아직 구동한 적 없음". PWM 이 지금 겨냥하는 축에만
                 의미가 있다.
        - step:  PWM4 가 켜져 있고 이 cs 가 활성 축임. STEP 신호는 모든 칩에
                 병렬로 닿지만 초퍼 ON(en=1)인 칩만 반응한다 — 그래서 현재
                 대상 cs 에만 step=1 을 단다.
        """
        return {
            "vmot": bool(self._chip_responsive.get(cs, False)),
            "en":   bool(self._chip_active.get(cs, False)),
            "sg":   bool(self._last_sg.get(cs, False)),
            "dir":  int(self._last_dir),
            "step": bool(self._pwm_active and self._active_axis == cs),
            "limit": self.limit_active(cs),
            "sg_value": int(self._last_sg_value.get(cs, 0)),
        }

    # -------------------------------------------------------------------
    # 중력 축 유지
    # -------------------------------------------------------------------
    def hold_cs_for(self, cs: int) -> int:
        """한 축의 유지 전류 스케일 (축별 재정의 우선)."""
        return int(self.hold_cs_map.get(cs, self.hold_cs))

    async def _hold_chip(self, cs: int) -> None:
        """`cs` 를 유지 전류로 여자한다 (유휴 역구동 방지)."""
        cap = self._cs_scale_cap
        try:
            self.apply_current_cap(min(cap, self.hold_cs_for(cs)))
            await self._init_chip(cs)
        finally:
            self.apply_current_cap(cap)

    async def _yield_held(self, active_cs: int) -> None:
        """다른 축이 움직이기 전에 유지 축을 풀어준다 — 공유 STEP 라인은
        여자된 모든 칩을 병렬로 스텝시켜 버린다."""
        for h in self.hold_axes - {active_cs}:
            if self._chip_active.get(h):
                try:
                    await self._silence_chip(h)
                except Exception as exc:
                    log.warning("yield held cs=%d failed: %s", h, exc)

    async def _finish_axis(self, cs: int) -> None:
        """모션 종료 시 칩 처리: 중력 축은 유지, 나머지는 침묵, 그 다음
        풀어줬던 축들을 다시 유지한다. E-STOP 후(_pwm_killed)에는 전부 침묵
        유지 — 여기서 재여자하면 E-STOP 의 칩 침묵을 되돌리는 셈이다."""
        try:
            if cs in self.hold_axes and not self._pwm_killed:
                await self._hold_chip(cs)
            else:
                await self._silence_chip(cs)
        except Exception:
            pass
        if not self._pwm_killed:
            for h in self.hold_axes - {cs}:
                try:
                    await self._hold_chip(h)
                except Exception as exc:
                    log.warning("re-hold cs=%d failed: %s", h, exc)

    # -------------------------------------------------------------------
    # 리밋 스위치 + 호밍
    # -------------------------------------------------------------------
    def limit_active(self, cs: int) -> bool | None:
        """한 cs 의 리밋 스위치 실시간 상태 (True = 눌림).

        ACTIVE LOW: PM-L25 분압기가 평시 high(~3 V)이고 플래그가 슬롯에
        들어오면 센서가 라인을 GND 로 당긴다. 스위치 미장착 축(FEED)이거나
        GPIO 가 아직 안 올라왔으면 None.
        """
        name = self._cs_to_limit.get(cs)
        if name is None or name not in self._gpio_inputs:
            return None
        chip_path, _ = self._gpio_map.get(name, (None, None))
        if chip_path is None or chip_path not in self._gpio_requests:
            return None
        try:
            return not self._gpio_get(name)
        except Exception:
            return None

    def _limit_tripped_debounced(self, cs: int) -> bool:
        """연속 두 번 읽기가 일치해야 한다 — 단일 샘플 노이즈를 걸러낸다."""
        return bool(self.limit_active(cs)) and bool(self.limit_active(cs))

    async def _home_move(
        self, cs: int, direction: int, freq_hz: int,
        max_steps: int, stop_when: str | None,
        fault_check_s: float = 0.25,
        stall_abort: bool = False,
    ) -> tuple[bool, int]:
        """호밍 세그먼트 하나: 리밋 조건이 맞거나 `max_steps` 가 지날
        때까지 `freq_hz` 로 STEP 을 돌린다.

        stop_when: 'trip' → 스위치가 눌리면 정지,
                   'release' → 스위치가 풀리면 정지,
                   None → 정확히 max_steps 만큼(고정 거리).
        (조건 충족 여부, 낸 스텝 수)를 돌려준다. 매 세그먼트 끝에서 PWM 은
        즉시 죽는다 — 호밍 속도는 모터 자기동 영역 안이라 램프가 필요 없고,
        정지는 폴링 한 주기 단위로 스텝 정확하다.
        """
        poll_s = 0.005
        self._set_dir(cs, direction)
        self._last_dir = 1 if direction > 0 else -1
        await asyncio.sleep(_DIR_SETUP_S)
        await self._pwm_ensure_exported()
        pos_start = self.positions.get(cs, 0)
        await self._pwm_set_hz(freq_hz)
        t0 = time.monotonic()
        met = False
        steps = 0
        next_fault_t = fault_check_s
        sg_hits = 0
        try:
            while steps < max_steps:
                await asyncio.sleep(poll_s)
                elapsed = time.monotonic() - t0
                steps = min(int(elapsed * freq_hz), max_steps)
                self.positions[cs] = pos_start + steps * (1 if direction > 0 else -1)
                if stop_when == 'trip' and self._limit_tripped_debounced(cs):
                    met = True
                    break
                if stop_when == 'release' and self.limit_active(cs) is False:
                    met = True
                    break
                if elapsed >= next_fault_t:
                    next_fault_t += fault_check_s
                    status = await self._read_status(cs)
                    if self._has_fault(status):
                        raise RuntimeError(
                            f"axis cs={cs} fault during homing (0x{status:05X})")
                    if stall_abort:
                        # StallGuard 를 가상 리밋 스위치로(중단 전용, datum
                        # 은 절대 아님 — AN-002). SG 연속 2회 = 기계적 접촉:
                        # 주행 한계에 닿은 것처럼 이 구간을 세운다.
                        if self._last_sg.get(cs):
                            sg_hits += 1
                            if sg_hits >= 2:
                                log.warning("home_move cs=%d: stall detected "
                                            "after %d steps — leg aborted", cs, steps)
                                break
                        else:
                            sg_hits = 0
        finally:
            await self._pwm_disable()
            self.positions[cs] = pos_start + steps * (1 if direction > 0 else -1)
        return met, steps

    async def home_axis(
        self, cs: int, direction: int,
        seek_hz: int, latch_hz: int, backoff_steps: int,
        timeout_s: float = 60.0, park_steps: int = 0,
        max_travel_steps: int | None = None,
        search_range_steps: int | None = None,
        reduced_cs: int = 0,
        rotary: bool = False,
        preprobe_steps: int = 0,
        stall_abort: bool = False,
    ) -> None:
        """한 축을 주행 중간의 창(window) 센서에 대고 호밍한다.

        CiA 402 방법 23-30 을 따른 양방향 탐색(엔드 리밋 스위치 대신 소프트
        주행 한계에 맞게 각색)에 GRBL 식 2패스 래치를 얹었다:

        S1 RELEASE   스위치 위에서 시작? 풀릴 때까지 후퇴(-dir) + 백오프.
        S2 PRIMARY   `direction` 으로 탐색, search_range_steps 로 제한 —
                     플래그는 창의 어느 쪽에든 있을 수 있으므로 "1차 구간에서
                     못 찾음"은 대개 반대쪽이라는 뜻이지 고장이 아니다.
        S3 REVERSE   -direction 으로 전체 주행(max_travel_steps)을 탐색.
                     그래도 없으면 → 센서 고장.
        S4 CANONICAL 풀릴 때까지 후퇴(-dir) + 백오프. 어느 구간이 창을
                     찾았든 여기서 '같은 쪽'으로 창을 나가므로 래치는 항상
                     한 방향에서 접근한다 — PM-L25 의 0.05 mm 히스테리시스와
                     비대칭 20/80 µs 응답 때문에 방향이 섞인 datum 은 스펙
                     0.01 mm 의 몇 배로 나빠지므로 필수다.
        S5 LATCH     `direction` 으로 느린 접근; datum = 눌림 에지.
        S6 PARK      park_steps=0 은 눌림 지점 위에 그대로 선다(이 기계의
                     홈 자세가 곧 스위치 위치다); park_steps>0 은 통상적
                     pull-off.

        reduced_cs > 0 이면 호밍 동안 전류 스케일 상한을 일시적으로 좁힌다
        (Duet M913 / Marlin *_CURRENT_HOME 관행) — 하드스톱 접촉이 부드럽게
        스톨하도록. 중력 축에는 쓰지 말 것.

        벤치 모션 태스크로 돈다: jog_stop / E-STOP 이 취소하며, 어느 쪽이든
        finally 블록이 칩을 침묵시킨다.
        """
        if self.limit_active(cs) is None:
            raise RuntimeError(f"axis cs={cs} has no limit switch configured")
        direction = 1 if direction > 0 else -1
        seek_hz = max(200, min(int(seek_hz), 2000))
        latch_hz = max(50, min(int(latch_hz), 500))
        backoff_steps = max(20, int(backoff_steps))
        # 주행 한계. 해제(release) 이동은 플래그 길이(백오프 10회)로
        # 제한한다: 그 안에 안 풀리는 스위치는 낀 것이다.
        if max_travel_steps is None:
            max_travel_steps = int(50 * 200)   # conservative 50-unit default
        if search_range_steps is None:
            search_range_steps = max_travel_steps
        max_primary = min(int(timeout_s * seek_hz), search_range_steps)
        max_reverse = min(int(timeout_s * seek_hz), max_travel_steps)
        max_release = backoff_steps * 10
        self._pwm_killed = False   # 새 모션 — E-STOP kill 래치 해제
        self._active_axis = cs
        cap_before = self._cs_scale_cap
        try:
            await self._yield_held(cs)   # 공유 STEP: 유지 축을 풀어준다
            if reduced_cs > 0:
                # 상한을 좁힌다(넓히는 일은 없다) — _init_chip 이 호밍
                # 이동에 더 순한 CS 를 쓰게 하고, finally 에서 복원한다.
                self.apply_current_cap(min(cap_before, int(reduced_cs)))
            await self._init_chip(cs)
            status = await self._read_status(cs)
            if self._has_fault(status):
                raise RuntimeError(f"axis cs={cs} fault before homing (0x{status:05X})")

            # S1 — 스위치 위에서 시작했다면 먼저 벗어난다
            if self._limit_tripped_debounced(cs):
                met, _ = await self._home_move(
                    cs, -direction, seek_hz, max_release, 'release')
                if not met:
                    raise RuntimeError(
                        f"axis cs={cs} limit stuck active — sensor/wiring "
                        f"suspect, aborting after bounded retreat")
                await self._home_move(cs, -direction, seek_hz, backoff_steps, None)
            elif preprobe_steps > 0 and not rotary:
                # S1b — 접근 방향의 '반대'로 사전 탐침: 중력 축에서 창 밖
                # 시작의 흔한 경우는 "창 바로 아래로 가라앉음"이고, 1차
                # 구간은 바닥 스톱으로 처박힐 것이다. 짧은 반대 방향 탐침이
                # 스톱을 건드리지 않고 그 경우를 잡는다.
                met, _ = await self._home_move(
                    cs, -direction, seek_hz, preprobe_steps, 'trip')
                if met:
                    log.info("home_axis cs=%d: window found on pre-probe", cs)
                    met, _ = await self._home_move(
                        cs, -direction, seek_hz, max_release, 'release')
                    if not met:
                        raise RuntimeError(
                            f"axis cs={cs} limit did not release after "
                            f"pre-probe — sensor stuck")
                    await self._home_move(
                        cs, -direction, seek_hz, backoff_steps, None)

            if not self._limit_tripped_debounced(cs):
                # S2 — 1차 탐색. 회전 축: 1회전에 창이 하나이므로 1회전+
                # 여유로 제한한 구간 하나가 반드시 창을 가로지른다 — 뒤집을
                # 필요 자체가 없다.
                met, _ = await self._home_move(
                    cs, direction, seek_hz, max_primary, 'trip',
                    stall_abort=stall_abort)
                if not met and rotary:
                    raise RuntimeError(
                        f"axis cs={cs} window not seen within one full "
                        f"revolution — check sensor power/wiring")
                if not met:
                    # S3 — 반대쪽에 있는 직선 축: 방향을 뒤집어 전체 주행을
                    # 탐색한다. 1차 구간이 캐리지를 하드스톱에 밀어 넣었을 수
                    # 있으므로, 첫 구간은 천천히 빠져나온 뒤 풀 탐색 속도로
                    # 간다.
                    log.info("home_axis cs=%d: window not in primary leg "
                             "(%d steps) — reversing", cs, max_primary)
                    met, _ = await self._home_move(
                        cs, -direction, latch_hz, backoff_steps * 2, 'trip')
                    if not met:
                        met, _ = await self._home_move(
                            cs, -direction, seek_hz, max_reverse, 'trip',
                            stall_abort=stall_abort)
                    if not met:
                        raise RuntimeError(
                            f"axis cs={cs} home window not found in either "
                            f"direction — check sensor power/wiring")

            # S4 — 정규화: -direction 쪽으로 창을 나간다 (두 구간 모두에
            # 성립: 1차는 -dir 에서 들어왔으니 되짚어 나가고, 역방향은 +dir
            # 에서 들어왔으니 관통해 나간다).
            met, _ = await self._home_move(
                cs, -direction, seek_hz, max_release, 'release')
            if not met:
                raise RuntimeError(
                    f"axis cs={cs} limit did not release on backoff — "
                    f"sensor stuck, aborting")
            await self._home_move(cs, -direction, seek_hz, backoff_steps, None)

            # 4) 느린 래치 패스
            met, _ = await self._home_move(
                cs, direction, latch_hz,
                backoff_steps * 4 + int(2.0 * latch_hz), 'trip')
            if not met:
                raise RuntimeError(f"axis cs={cs} latch pass missed the switch")

            # 5) (재현 가능한) 저속 눌림 지점을 datum 으로
            self.positions[cs] = 0

            # 6) 파킹. >0 = 통상적 pull-off(창 밖), <0 = 창 '안으로' 전진해
            # 정지 상태에서 센서가 확실한 눌림으로 읽히게 한다 — 눌림 에지
            # 자체가 센서 히스테리시스 밴드 안에 있어 무작위로 clear/눌림이
            # 읽힌다(실관측: 0 에 파킹한 BEND 는 clear, LIFT 는 눌림).
            if park_steps > 0:
                await self._home_move(cs, -direction, seek_hz, park_steps, None)
            elif park_steps < 0:
                await self._home_move(cs, direction, latch_hz, -park_steps, None)
            log.info("home_axis cs=%d complete: datum set, resting at %+d steps",
                     cs, self.positions[cs])
        finally:
            # 저전류 호밍을 위해 좁혔던 주행 전류 상한을 복원한다.
            if reduced_cs > 0:
                self.apply_current_cap(cap_before)
            try:
                await self._pwm_disable()
            except Exception:
                pass
            await self._finish_axis(cs)
            self._save_state_soon()
            if self._active_axis == cs:
                self._active_axis = None

    # -------------------------------------------------------------------
    # 내부: TMC260C 초기화 / 침묵 / 상태
    # -------------------------------------------------------------------
    def apply_current_cap(self, cs_cap: int) -> None:
        """_init_chip 이 쓰는 SGCSCONF 전류 스케일을 좁힌다.

        main.py 가 PsuService.cs_cap 으로 호출한다(운전자가 PSU 프리셋을
        바꿀 때마다 다시). 이것이 없으면 선택된 전원과 무관하게 모든 조그가
        SGCSCONF_DEFAULT(CS=19)를 썼다 — UnsafeRegisterWrite 가드는
        /diag/register 경로만 지킨다. 상한은 좁아지기만 한다:
        SAFETY_CS_MAX 로 클램프된다.
        """
        capped = max(0, min(int(cs_cap), SAFETY_CS_MAX))
        if capped != self._cs_scale_cap:
            log.info("SGCSCONF current cap: CS ≤ %d (PSU-derived)", capped)
        self._cs_scale_cap = capped

    def run_cs_for(self, cs: int) -> int:
        """모든 클램프를 거친 뒤의, 한 축의 주행 전류.

        CS=31 로 보드 2장이 소손됐으므로(2026-05-08) 축 설정은 *좁히는*
        것만 허용된다: PSU 유도 상한, 그 다음 SAFETY_CS_MAX 순서로 제한된다.
        이 함수를 포함해 어떤 호출자도 넓힐 수 없다.
        """
        want = int(self.run_cs_map.get(cs, SGCSCONF_DEFAULT & 0x1F))
        return max(0, min(want, self._cs_scale_cap, SAFETY_CS_MAX))

    def effective_cs(self, cs: int | None = None) -> int:
        """칩에 실제로 쓰이는 코일 전류 스케일 (0-31)."""
        if cs is None:
            return min(SGCSCONF_DEFAULT & 0x1F, self._cs_scale_cap,
                       SAFETY_CS_MAX)
        return self.run_cs_for(cs)

    def sgt_for(self, cs: int) -> int:
        """한 축의 StallGuard 임계값 (-64..63, 클수록 덜 민감)."""
        default_sgt = (SGCSCONF_DEFAULT >> 8) & 0x7F
        if default_sgt > 63:
            default_sgt -= 128
        return int(self.sgt_map.get(cs, default_sgt))

    def _drvctrl_for(self, cs: int) -> int:
        """한 축의 DRVCTRL: 축별 MRES 재정의 + DEDGE/INTPOL 비트 보존.

        DEDGE 를 지우면 실효 스텝 레이트가 조용히 반토막 난다(과거 사고,
        tmc260c_driver.set_microstep 주석 참조) — 마스크가 그것을 막는다.
        """
        mres = self.mres_map.get(cs)
        if mres is None:
            return DRVCTRL_DEFAULT
        return (DRVCTRL_DEFAULT & ~0x0F) | (int(mres) & 0x0F)

    def _sgcs_on_value(self, cs: int | None = None) -> int:
        """한 축의 SGCSCONF: PSU 상한이 걸린 전류 스케일 + 그 축의 SGT.

        레이아웃: bit16 SFILT, bits 8-14 SGT (부호 있는 7비트), bits 0-4 CS.
        """
        current = self.run_cs_for(cs) if cs is not None else min(
            SGCSCONF_DEFAULT & 0x1F, self._cs_scale_cap, SAFETY_CS_MAX)
        sgt = self.sgt_for(cs) if cs is not None else (
            (SGCSCONF_DEFAULT >> 8) & 0x7F)
        return ((1 if self.sg_filter else 0) << 16) | ((sgt & 0x7F) << 8) | current

    async def _init_chip(self, cs: int) -> int:
        """지연 초기화: 첫 호출은 풀 SEQ, 이후는 빠른 초퍼 재활성.

        마지막으로 보낸 프레임 시점의 20비트 status word 를 돌려주므로,
        호출자의 구동 전 폴트 확인에 추가 SPI 왕복이 필요 없다.

        TMC260C 레지스터(CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF)는
        전원 유실이나 새 쓰기 전까지 칩에 유지된다. 한 번 초기화되면 이후의
        침묵→조그 사이클은 CHOPCONF(TOFF)와 SGCSCONF(CS)만 토글해 초퍼를
        껐다 켜면 된다. 이것이 짧은 버튼 탭을 기민하게 만든다
        (~15 ms vs ~375 ms).

        풀 초기화 루프는 유효한 SPI 응답이 _INIT_GOOD_CYCLES_EXIT 회
        연속되면(최소 _INIT_SEQ_MIN_CYCLES 사이클 이후) 조기 종료한다 —
        전원이 없거나 부재한 칩은 0x00000/0xFFFFF 를 돌려주므로 여전히 50
        사이클을 다 돈다.
        """
        if self._initialized.get(cs, False):
            # 빠른 재활성: 초퍼 on + 전류 스케일, 그리고 그 뒤의 status
            # 읽기까지 '한' 배치로. 구동 전 폴트 확인이 예전에는 별도의
            # spi_transfer 였다 — 어차피 나가는 프레임들에 얹을 수 있는 한
            # 프레임을 위해 락 획득과 스레드 홉을 한 번 더(~0.6 ms 실측)
            # 지불했던 것이다.
            chopconf_on = self._encode(0x04, CHOPCONF_DEFAULT)
            sgcs_on     = self._encode(0x06, self._sgcs_on_value(cs))
            tx_chop = bytes([(chopconf_on >> 16) & 0xFF, (chopconf_on >> 8) & 0xFF, chopconf_on & 0xFF])
            tx_sgcs = bytes([(sgcs_on >> 16) & 0xFF, (sgcs_on >> 8) & 0xFF, sgcs_on & 0xFF])
            rx = await self.spi_transfer_batch(
                cs, [tx_chop, tx_sgcs] * _REENABLE_CYCLES
                    + [self._status_frame()])
            self._chip_active[cs] = True
            self._chip_responsive[cs] = True
            return self._note_status(cs, rx[-1])

        # 한 번도 건드린 적 없는 칩의 1회성 풀 초기화
        good_cycles = 0
        for cycle in range(_INIT_SEQ_CYCLES_FULL):
            rx = b"\x00\x00\x00"
            for _name, tag, value in _INIT_SEQ:
                if tag == 0x06:  # SGCSCONF: PSU 상한 전류 + 축별 SGT
                    value = self._sgcs_on_value(cs)
                elif tag == 0x00:  # DRVCTRL: 축별 MRES (DEDGE/INTPOL 보존)
                    value = self._drvctrl_for(cs)
                datagram = self._encode(tag, value)
                tx = bytes([
                    (datagram >> 16) & 0xFF,
                    (datagram >> 8)  & 0xFF,
                    datagram         & 0xFF,
                ])
                rx = await self.spi_transfer(cs, tx)
            status = ((rx[0] << 16) | (rx[1] << 8) | rx[2]) & 0xFFFFF
            if status not in (0x00000, 0xFFFFF):
                good_cycles += 1
            else:
                good_cycles = 0
            if (cycle + 1 >= _INIT_SEQ_MIN_CYCLES
                    and good_cycles >= _INIT_GOOD_CYCLES_EXIT):
                log.info("axis cs=%d init early-exit after %d cycles", cs, cycle + 1)
                break
        self._initialized[cs] = True
        self._chip_active[cs] = True
        self._chip_responsive[cs] = True
        log.info("axis cs=%d full init done (one-time)", cs)
        return self._note_status(cs, rx)

    async def _silence_chip(self, cs: int) -> None:
        """초퍼 비활성(TOFF=0) + 전류 0.

        칩의 나머지 레지스터 상태는 그대로 둬서 다음 _init_chip() 호출이
        빠른 재활성 경로를 탈 수 있게 한다.
        """
        # CHOPCONF=0x80000 (TOFF=0 → 초퍼 비활성)
        chop_off = self._encode(0x04, 0x80000)
        sgcs_off = self._encode(0x06, 0xD3F00)  # CS=0
        tx_chop = bytes([
            (chop_off >> 16) & 0xFF, (chop_off >> 8) & 0xFF, chop_off & 0xFF,
        ])
        tx_sgcs = bytes([
            (sgcs_off >> 16) & 0xFF, (sgcs_off >> 8) & 0xFF, sgcs_off & 0xFF,
        ])
        await self.spi_transfer_batch(
            cs, [tx_chop, tx_sgcs] * _SILENCE_CYCLES)
        # 주의: self._initialized 를 지우지 말 것 — 칩의 CHOPCONF/SMARTEN/
        # DRVCONF/DRVCTRL 은 여전히 초기화된 값이다. 다음 _init_chip() 은
        # 빠른 재활성 경로를 탄다.
        # LED 행을 위해 초퍼 off 를 표시한다. 칩은 여전히 응답한다고 본다
        # (방금 대화했으니까).
        self._chip_active[cs] = False
        self._chip_responsive[cs] = True

    def _status_frame(self) -> bytes:
        """응답이 20비트 status word 인 DRVCONF 데이터그램.

        칩은 모든 프레임에 현재 유효한 RDSEL 포맷의 status word 로 답하므로,
        DRVCONF(RDSEL=01)를 다시 보내는 것은 읽기이자 "돌아오는 것은
        SG_VAL"이라는 재확인이다 — diag 레지스터 경로가 RDSEL 을 딴 데
        둘 수 있으니 유지할 가치가 있다.
        """
        datagram = self._encode(0x07, DRVCONF_DEFAULT & 0x1FFFF)
        return bytes([
            (datagram >> 16) & 0xFF, (datagram >> 8) & 0xFF, datagram & 0xFF,
        ])

    def _note_status(self, cs: int, rx: bytes) -> int:
        """status 응답 하나를 해독해 캐시한다. _read_status 와 _init_chip 이
        공유한다 — 후자는 이제 어차피 보내던 프레임에서 status 를 얻고, 그걸
        위해 SPI 왕복을 한 번 더 지불하지 않는다."""
        status = ((rx[0] << 16) | (rx[1] << 8) | rx[2]) & 0xFFFFF
        # LED 행을 위해 SG 비트와 응답성을 캐시한다. VMot 이 죽으면 SPI
        # 라인이 0xFF 로 뜨므로 0xFFFFF 읽기는 "전원 없음"이다.
        self._chip_responsive[cs] = (status != 0xFFFFF and status != 0)
        self._last_sg[cs] = bool(status & 0x01)
        self._last_sg_value[cs] = (status >> 10) & 0x3FF
        self._last_status[cs] = status
        return status

    async def _read_status(self, cs: int) -> int:
        """DRVCONF(RDSEL=01 → SG_VAL)를 보내 20비트 status 를 읽는다."""
        rx = await self.spi_transfer(cs, self._status_frame())
        return self._note_status(cs, rx)

    @staticmethod
    def _has_fault(status: int) -> bool:
        """OT/OTPW/S2GA/S2GB/OLA/OLB 비트(bit 1..6)를 확인한다.

        SG(bit 0, StallGuard2 스톨 표시)는 의도적으로 하드 폴트로 다루지
        않는다 — StallGuard2 임계값은 정상 가속 중과 고르지 않은 부하에서
        일시적으로 발화할 수 있다. 반복 스톨은 _is_persistent_stall() 이
        따로 검출한다.
        """
        return bool((status & 0xFF) & 0x7E)

    @staticmethod
    def _is_stall(status: int) -> bool:
        """SG 비트 (StallGuard2 스톨 표시)."""
        return bool(status & 0x01)

    @staticmethod
    def _encode(reg_tag: int, value: int) -> int:
        """레지스터 태그 + 값으로 20비트 데이터그램을 인코딩 (tmc260c_driver 와 동일)."""
        if reg_tag == 0x00:  # DRVCTRL
            return value & 0xFFFFF
        return ((reg_tag & 0x07) << 17) | (value & 0x1FFFF)

    # -------------------------------------------------------------------
    # PWM4 제어 (STEP 신호, 3개 칩에 병렬)
    # -------------------------------------------------------------------
    async def _ramp(self, f_from: int, f_to: int, rate_hz_s: float,
                    shape: str = "linear",
                    track: tuple[int, int] | None = None,
                    guard_cb=None, abort_cb=None, remaining_cb=None) -> int:
        """PWM 주파수를 f_from → f_to 로 슬루한다. 낸 것으로 추정되는
        STEP 에지 수(일정의 사다리꼴 적분)를 돌려주며, track=(cs, direction)
        이면 틱마다 위치 카운터를 실시간 갱신한다.

        linear: 일정 기울기 = rate_hz_s (사다리꼴 속도).
        scurve: smoothstep 일정 f(τ) = f0 + Δf·(3τ²−2τ³) — 저크 제한,
        C1 연속 가속. T 는 '피크' 기울기가 rate_hz_s 와 같도록 잡는다
        (부드러움이 설정 가속도를 넘어서는 일은 없다). ~30 ms 틱에서는
        스텝 단위 셰이핑이 아니라 주파수 일정이다 — 벤치 PWM 경로에는
        충분하다.
        """
        span = abs(f_to - f_from)
        if span == 0 or rate_hz_s <= 0:
            await self._pwm_set_hz(f_to)
            return 0
        if shape == "scurve":
            total_s = 1.5 * span / rate_hz_s   # smoothstep peak slope = 1.5·Δf/T
        else:
            total_s = span / rate_hz_s
        # 하한은 한 틱이 아니라 한 서브슬립: 그 밑에서는 램프가 PWM 쓰기
        # 한 번이고, 일정이 표현할 것이 남지 않는다.
        total_s = max(total_s, _RAMP_SUBSLEEP_MIN_S)
        n_ticks, tick_s = _ramp_tick_plan(total_s)

        base = self.positions.get(track[0], 0) if track else 0
        t = 0.0
        steps = 0.0
        f_cur = float(f_from)          # PWM 이 '지금' 돌고 있는 주파수
        t_wall0 = time.monotonic()
        last = t_wall0
        aborted = False

        def account(now: float) -> None:
            """마지막 정산 시점 이후 나간 에지를, PWM 이 '실제로' 돌던
            주파수로 계상한다.

            이상적 일정의 재생이 아니라 실시간 적분이다: 루프의 실제 틱
            길이는 표류하고(10 ms 가드 서브슬립, sysfs 쓰기, 스케줄러 지터),
            일정 모델은 그때 계수를 틀린다 — 처음엔 적게(축이 과주행),
            꼬리 항을 더하면 많게(축이 미달)."""
            nonlocal steps, last
            steps += f_cur * (now - last)
            last = now
            if track:
                self.positions[track[0]] = base + int(steps) * track[1]

        try:
            while t < total_s and not aborted:
                # 리밋 가드가 틱 안에서 반응할 수 있도록 10 ms 조각으로
                # 서브슬립한다 — 빠른 축은 센서 창을 수십 ms 에 가로지른다.
                slept = 0.0
                while slept < tick_s:
                    # 목표를 지나쳐 자지 않는다. 고정 조각은 abort_cb 를
                    # 묻기 전에 f_cur x 조각만큼 스텝을 내보낸다 -- 400 Hz 면
                    # 4 스텝인데 그게 0.1 mm 이동의 오차 예산 전부다. 축이
                    # 다가갈수록 조각을 줄이면 과주행이 약 1 스텝으로
                    # 묶인다.
                    slice_s = min(_RAMP_SUBSLEEP_S, tick_s - slept)
                    if remaining_cb is not None and f_cur > 0:
                        rem = remaining_cb()
                        if rem > 0:
                            slice_s = min(slice_s, rem / f_cur)
                        slice_s = max(_RAMP_SUBSLEEP_MIN_S, slice_s)
                    await asyncio.sleep(slice_s)
                    slept += slice_s
                    account(time.monotonic())
                    if guard_cb is not None and guard_cb():
                        aborted = True
                        break
                    # 거리 기반 중단: 제동거리가 목표를 넘겨 버리는 순간
                    # 가속을 멈춘다.
                    if abort_cb is not None and abort_cb():
                        aborted = True
                        break
                if aborted:
                    break
                t = min(total_s, t + tick_s)
                tau = t / total_s
                s = tau * tau * (3.0 - 2.0 * tau) if shape == "scurve" else tau
                f_next = int(round(f_from + (f_to - f_from) * s))
                await self._pwm_set_hz(f_next)
                account(time.monotonic())   # 이 틱을 이전 주파수로 마감
                f_cur = float(f_next)       # 새 설정값은 여기서부터 유효
        finally:
            account(time.monotonic())
            # 램프가 이상적 일정보다 실제로 얼마나 더 걸렸는지. pulse_step
            # 이 감속 예약량을 이걸로 잡아서, 이동이 지령 거리를 넘치거나
            # 모자라지 않고 착지한다.
            if total_s > 0:
                self._ramp_jitter = max(
                    1.0, min(3.0, (time.monotonic() - t_wall0) / total_s))
        return int(steps)

    def _ramp_steps_est(self, f_from: int, f_to: int, total_s: float,
                        shape: str) -> int:
        """아직 돌지 않은 램프의 STEP 에지 추정치.

        매끈한 적분이 아니라 실제 동작을 흉내 낸다: PWM 은 설정값 하나를 틱
        내내 유지하다 틱 끝에서만 바뀌고, 모든 틱은 직전 램프에서 실측한
        지터 계수만큼 길게 돈다. 감속 거리 예약에 쓰인다.
        """
        if total_s <= 0:
            return 0
        jit = getattr(self, "_ramp_jitter", 1.0)
        n, tick = _ramp_tick_plan(total_s)
        est = 0.0
        f = float(f_from)
        for i in range(1, n + 1):
            est += f * tick * jit
            tau = i / n
            s = tau * tau * (3.0 - 2.0 * tau) if shape == "scurve" else tau
            f = f_from + (f_to - f_from) * s
        return int(est)

    async def _pwm_ensure_exported(self) -> None:
        if not os.path.isdir(self._pwm_path):
            try:
                with open(self._pwm_export, 'w') as f:
                    f.write('0\n')
                await asyncio.sleep(0.05)
            except Exception as exc:
                log.error("PWM export failed: %s", exc)
                raise

    async def _pwm_set_hz(self, hz: int) -> None:
        """돌고 있는 STEP 열에 공백을 내지 않고 PWM 을 `hz` 로 설정한다.

        첫 활성화는 안전한 duty=0 → period → duty → enable 순서를 쓴다.
        이미 켜져 있으면 period/duty 만 다시 쓰되, 매 순간
        duty_cycle ≤ period 를 유지하는 순서로 쓴다(sysfs PWM API 가
        아니면 쓰기를 거부한다):
          - period 가 커질 때:  period 먼저, 그 다음 duty
          - period 가 작아질 때: duty 먼저(새 duty < 옛 period), 그 다음 period
        예전 구현은 램프 틱마다 duty=0/enable 춤을 전부 다시 췄다 — 틱마다
        죽은 STEP 주기 최대 한 개, 즉 소프트 스타트마다 12번의 스텝 유실.
        """
        if self._pwm_killed:
            return   # E-STOP 이 PWM 을 죽였다 — 취소가 도착할 때까지 램프 틱 무시
        period = int(1e9 / hz)
        duty   = period // 2
        try:
            if not self._pwm_enabled:
                with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write('0\n')
                with open(f"{self._pwm_path}/period",     'w') as f: f.write(f"{period}\n")
                with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write(f"{duty}\n")
                with open(f"{self._pwm_path}/enable",     'w') as f: f.write('1\n')
                self._pwm_enabled = True
            elif period >= self._pwm_last_period_ns:
                with open(f"{self._pwm_path}/period",     'w') as f: f.write(f"{period}\n")
                with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write(f"{duty}\n")
            else:
                with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write(f"{duty}\n")
                with open(f"{self._pwm_path}/period",     'w') as f: f.write(f"{period}\n")
            self._pwm_last_period_ns = period
            self._pwm_active = True
        except Exception as exc:
            log.error("PWM set %d Hz failed: %s", hz, exc)
            self._pwm_enabled = False
            raise

    async def _pwm_disable(self, kill: bool = False) -> None:
        """STEP 출력을 멈춘다. kill=True(E-STOP 경로)는 PWM off 를 래치해
        동시에 도는 램프 틱이 되켜지 못하게 한다."""
        if kill:
            self._pwm_killed = True
        try:
            with open(f"{self._pwm_path}/enable", 'w') as f:
                f.write('0\n')
        except Exception:
            pass
        self._pwm_active = False
        self._pwm_enabled = False
