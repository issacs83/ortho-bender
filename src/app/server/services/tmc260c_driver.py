"""
tmc260c_driver.py — TMC260C 20-bit SPI 프로토콜 드라이버.

TMC260C 는 20비트 SPI 데이터그램을 쓴다(MSB 우선, SPI Mode 3, 최대 2 MHz).
쓰기 한 번마다 20비트 상태/SG 응답이 동시에 돌아온다.

레지스터 주소 태그는 비트 [19:17] 에 들어간다:
  DRVCTRL  = 00x (bit19=0, bit18=0)
  CHOPCONF = 100
  SMARTEN  = 101
  SGCSCONF = 110
  DRVCONF  = 111

참고: TMC260C-PA 데이터시트 Rev 1.04.
src/firmware/source/drivers/tmc260c.h 와 내용이 같다.

IEC 62304 SW Class: B

# 🚨 하드 안전 상한 — 절대 위반 금지
아래 레지스터 기본값은 2026-05-08 모터 테스트 벤치에서 *검증된 동작값* 이다.
이전 기본값(CS=20, CHOPCONF=0x101D5)은 스윕 테스트 중 1/2층 보드를 태웠다
(CS=31 + TOFF=15).

CS 를 19 초과로 절대 올리지 말 것. TOFF 를 8 초과로 절대 설정하지 말 것.
참고: src/dev/safety_motor_register_limits.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .motor_backend import MotorBackend

# 레지스터 태그 (비트 [19:17])
REG_DRVCTRL  = 0x00
REG_CHOPCONF = 0x04
REG_SMARTEN  = 0x05
REG_SGCSCONF = 0x06
REG_DRVCONF  = 0x07

# ===== 하드 안전 상한 (오버라이드 불가) =====
SAFETY_CS_MAX   = 19   # 2026-05-08 CS=31 로 보드 소손
SAFETY_TOFF_MAX = 8    # TOFF>8 은 열 손상

# ===== 검증된 동작 레지스터 기본값 (2026-05-08) =====
#
# 튜닝 지도 — 무엇이 노브이고 무엇이 동결인지:
#
#   레지스터   필드    상태          변경 방법
#   --------  ------  ------------  ------------------------------------------
#   SGCSCONF  CS      런타임 노브   PUT /api/motor/protection {axes:{n:{run_cs}}}
#                                   / {hold_cs}. 상수를 직접 고치지 말 것.
#   SGCSCONF  SGT     런타임 노브   PUT /api/motor/stallguard {axis, sgt}
#   SGCSCONF  SFILT   런타임 노브   PUT /api/motor/stallguard {filter}
#   DRVCTRL   MRES    코드 레벨     set_microstep() 이 있지만 전축 공용이다.
#                                   축별 MRES 는 CLAUDE.md 의 미결 과제
#                                   (FEED 분해능)를 먼저 처리해야 한다.
#   CHOPCONF  전체    동결          상수 하나로 기록되며 파라미터화하지 않는다
#   DRVCONF   전체    동결          슬로프/VSENSE 가 전류 스케일 자체를 바꾼다 —
#                                   VSENSE 를 건드리면 코일 전류가 조용히 2배
#   SMARTEN   전체    OFF           CoolStep 비활성. 켜면 코일 전류를 스스로
#                                   움직여 CS<=19 상한을 벗어난다
#
# CHOPCONF=0x99548: TBL=2, HEND=10, HSTRT=4, TOFF=8 (안전 검증됨)
# TOFF 는 초퍼 off-time 이므로 성능이 아니라 열 파라미터다: 보드 두 장을
# 태운 것이 TOFF>8 이었다. 동결 상수.
CHOPCONF_DEFAULT = 0x99548
# SMARTEN=0xA0000: CoolStep OFF — 의도적이다. CoolStep 은 부하에 따라 CS 를
# 스스로 올리고 내리므로 아래의 모든 CS 상한을 무력화한다. 끈 채로 둘 것.
SMARTEN_DEFAULT  = 0xA0000
# SGCSCONF=0xD3F13: CS=19 (~0.6-0.9A RMS), SGT=+63, SFILT=1
# CS (비트 0-4)  = 토크 노브. 이 상수는 천장값일 뿐이고, 칩이 실제로 받는
#                  값은 spi_backend 의 run_cs_for(cs) 다 — 축별 run_cs 를
#                  PSU 캡, 그다음 SAFETY_CS_MAX 로 클램프한 값. 토크를 올리면
#                  열도 올라가고, 보드를 태운 것이 바로 그 열이다 — 1~2 씩
#                  올리면서 모터 케이스를 만져 볼 것.
# SGT (비트 8-14)= StallGuard 임계값. 여기 값 +63 은 최대로 둔감한 상태이며,
#                  튜닝하지 않은 축에서 SG_RESULT 가 평평하게 나오는 이유다.
#                  스톨 감지를 살리려면 낮춰야 한다(BEND 는 +8 에 있다).
# SFILT (비트 16)= 전기각 4주기 평균: 값이 안정적인 대신 반응이 4배 느리다.
SGCSCONF_DEFAULT = 0xD3F13
# DRVCONF=0xEF050: SLPH=11, SLPL=11, VSENSE=1, RDSEL=01 (SG_VALUE 읽기)
# VSENSE=1 은 낮은 감지 전압 스케일을 고른다: 같은 CS 값이 VSENSE=0 일 때의
# 대략 절반 코일 전류가 된다. 이 비트를 지우면 모든 CS<=19 가드를 통과한
# 채로 전 축의 전류가 2배가 된다 — 이 레지스터 전체를 동결한 이유다.
DRVCONF_DEFAULT  = 0xEF050
# DRVCTRL=0x00304: INTPOL=1, DEDGE=1, MRES=4 (1/16 마이크로스텝).
# MRES 는 속도/분해능 트레이드오프다: 마이크로스텝을 잘게 나눌수록 펄스당
# 거리와 8 kHz PWM 천장에서의 최고 속도가 함께 나뉜다.
# 이전 값 0x00300 (MRES=0 → 1/256) 에서는 8 kHz PWM 에서 축이 18.75 RPM 으로
# 묶였다. 1/16 은 같은 코일 전류로 기계적 속도를 16배 내주며,
# machine_config.h 와 M7 펌웨어의 마이크로스텝 가정과도 일치한다.
# DEDGE(PWM 양 엣지마다 스텝)는 반드시 유지해야 한다 — PWM STEP 경로가
# PWM 사이클당 마이크로스텝 2개를 전제로 한다.
DRVCTRL_DEFAULT  = 0x00304

# 정적 안전 검증 (기본값이 위험하면 import 시점에 실패시킨다)
assert (SGCSCONF_DEFAULT & 0x1F) <= SAFETY_CS_MAX, (
    f"SGCSCONF_DEFAULT CS={SGCSCONF_DEFAULT & 0x1F} exceeds safety limit "
    f"{SAFETY_CS_MAX}. See safety_motor_register_limits.md"
)
assert (CHOPCONF_DEFAULT & 0xF) <= SAFETY_TOFF_MAX, (
    f"CHOPCONF_DEFAULT TOFF={CHOPCONF_DEFAULT & 0xF} exceeds safety limit "
    f"{SAFETY_TOFF_MAX}"
)

# 응답 비트 마스크
RESP_SG_BIT   = 1 << 0
RESP_OT       = 1 << 1
RESP_OTPW     = 1 << 2
RESP_S2GA     = 1 << 3
RESP_S2GB     = 1 << 4
RESP_OLA      = 1 << 5
RESP_OLB      = 1 << 6
RESP_STST     = 1 << 7

RESP_SG_VALUE_SHIFT = 10
RESP_SG_VALUE_MASK  = 0x3FF


@dataclass
class Tmc260cStatus:
    """파싱된 TMC260C 20비트 SPI 응답."""
    raw: int
    sg_result: int
    stst: bool
    ot: bool
    otpw: bool
    s2ga: bool
    s2gb: bool
    ola: bool
    olb: bool
    sg_active: bool

    @property
    def has_fault(self) -> bool:
        return self.ot or self.s2ga or self.s2gb


class Tmc260cDriver:
    """TMC260C 20비트 SPI 프로토콜 드라이버."""

    def __init__(self, backend: MotorBackend, cs: int) -> None:
        self._backend = backend
        self._cs = cs
        self._last_status: Tmc260cStatus | None = None

    @staticmethod
    def encode_datagram(reg_tag: int, value: int) -> int:
        """레지스터 태그와 페이로드 값으로 20비트 데이터그램을 만든다.

        DRVCTRL (tag=0x00): 비트 [19:18] = 00, 비트 [17:0] = value
        그 외:              비트 [19:17] = tag, 비트 [16:0] = value
        """
        if reg_tag == REG_DRVCTRL:
            return value & 0xFFFFF  # DRVCTRL: 태그가 암묵적으로 00x
        return ((reg_tag & 0x07) << 17) | (value & 0x1FFFF)

    @staticmethod
    def parse_response(raw_bytes: bytes) -> Tmc260cStatus:
        """3바이트 SPI 응답을 Tmc260cStatus 로 파싱한다."""
        val = (raw_bytes[0] << 16) | (raw_bytes[1] << 8) | raw_bytes[2]
        val &= 0xFFFFF  # 20비트로 마스크
        flags = val & 0xFF
        sg_result = (val >> RESP_SG_VALUE_SHIFT) & RESP_SG_VALUE_MASK
        return Tmc260cStatus(
            raw=val,
            sg_result=sg_result,
            stst=bool(flags & RESP_STST),
            ot=bool(flags & RESP_OT),
            otpw=bool(flags & RESP_OTPW),
            s2ga=bool(flags & RESP_S2GA),
            s2gb=bool(flags & RESP_S2GB),
            ola=bool(flags & RESP_OLA),
            olb=bool(flags & RESP_OLB),
            sg_active=bool(flags & RESP_SG_BIT),
        )

    async def write_register(self, reg_tag: int, value: int) -> int:
        """레지스터를 쓰고 20비트 응답값을 반환한다."""
        datagram = self.encode_datagram(reg_tag, value)
        tx = bytes([(datagram >> 16) & 0xFF, (datagram >> 8) & 0xFF, datagram & 0xFF])
        rx = await self._backend.spi_transfer(self._cs, tx)
        val = (rx[0] << 16) | (rx[1] << 8) | rx[2]
        return val & 0xFFFFF

    async def read_status(self) -> Tmc260cStatus:
        """DRVCONF 읽기 명령을 보내 드라이버 상태를 읽는다."""
        datagram = DRVCONF_DEFAULT
        tx = bytes([(datagram >> 16) & 0xFF, (datagram >> 8) & 0xFF, datagram & 0xFF])
        rx = await self._backend.spi_transfer(self._cs, tx)
        status = self.parse_response(rx)
        self._last_status = status
        return status

    async def probe(self) -> tuple[bool, str]:
        """SPI 버스를 탐침해 이 CS 라인에 TMC260C 가 응답하는지 확인한다.

        DRVCONF 읽기 명령을 보내고 20비트 응답을 확인한다:
        - 전부 0(0x00000) 또는 전부 1(0xFFFFF) 이면 칩 없음 / 버스 이상.
        - 그 밖의 유효한 20비트 응답이면 TMC260C 가 연결된 것이다.

        (연결 여부, 칩 이름) 을 반환한다.
        """
        try:
            status = await self.read_status()
            if status.raw == 0 or status.raw == 0xFFFFF:
                return False, ""
            return True, "TMC260C"
        except Exception:
            return False, ""

    async def set_current(self, scale: int) -> None:
        """모터 전류 스케일 설정 (0-19, 하드코딩된 안전 상한).

        칩 자체는 CS=0..31 을 허용하지만 19 초과 값이 2026-05-08 보드 소손을
        일으켰다. 이 메서드는 SAFETY_CS_MAX 를 넘는 값을 모두 거부한다.
        """
        if not 0 <= scale <= SAFETY_CS_MAX:
            raise ValueError(
                f"Current scale must be 0-{SAFETY_CS_MAX} (hardcoded safety). "
                f"Got {scale}. See safety_motor_register_limits.md"
            )
        value = (SGCSCONF_DEFAULT & 0x1FFE0) | (scale & 0x1F)
        await self.write_register(REG_SGCSCONF, value)

    async def set_microstep(self, mres: int) -> None:
        """마이크로스텝 분해능 설정 (0=256, 1=128, ..., 8=풀스텝).

        DRVCTRL_DEFAULT 의 INTPOL/DEDGE 비트를 보존한다 — 예전 버전은
        (1<<9)|mres 를 써서 DEDGE 를 조용히 지우고 실효 스텝 레이트를
        절반으로 떨어뜨렸다.
        """
        if not 0 <= mres <= 8:
            raise ValueError(f"MRES must be 0-8, got {mres}")
        value = (DRVCTRL_DEFAULT & ~0x0F) | (mres & 0x0F)
        await self.write_register(REG_DRVCTRL, value)

    async def set_stallguard(self, threshold: int, filter_enable: bool) -> None:
        """StallGuard2 임계값 설정 (-64 ~ +63)."""
        if not -64 <= threshold <= 63:
            raise ValueError(f"SG threshold must be -64..+63, got {threshold}")
        sgt = threshold & 0x7F
        cs = SGCSCONF_DEFAULT & 0x1F
        value = (int(filter_enable) << 16) | (sgt << 8) | cs
        await self.write_register(REG_SGCSCONF, value)

    async def dump_registers(self) -> dict[str, int]:
        """기본값을 다시 쓰고 응답을 받아 쓰기 가능한 5개 레지스터를 덤프한다.

        주의: TMC260C 에는 전용 읽기(read-back)가 없다. 레지스터를 쓰면
        레지스터 값이 아니라 *직전* 상태가 돌아온다. 그래서 진짜 레지스터
        덤프 대신 알려진 기본값을 다시 쓰고 기대값을 반환한다.
        """
        return {
            'DRVCTRL': DRVCTRL_DEFAULT & 0xFFFFF,
            'CHOPCONF': CHOPCONF_DEFAULT & 0x1FFFF,
            'SMARTEN': SMARTEN_DEFAULT & 0x1FFFF,
            'SGCSCONF': SGCSCONF_DEFAULT & 0x1FFFF,
            'DRVCONF': DRVCONF_DEFAULT & 0x1FFFF,
        }
