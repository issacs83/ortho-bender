"""
motor_service.py — 모터 제어 서비스 계층.

REST API 호출을 M7 FreeRTOS 코어로 보내는 IPC 명령으로 변환한다.
MSG_STATUS_MOTION 응답을 AxisStatus 객체로 디코딩한다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import struct
import logging
from typing import Optional

from ..models.schemas import (
    AxisSignals,
    AxisId,
    AxisStatus,
    MotionState,
    MotorStatusResponse,
)
from .tmc260c_driver import SAFETY_CS_MAX, SGCSCONF_DEFAULT
from .ipc_client import (
    IpcClient,
    MSG_MOTION_EXECUTE_BCODE,
    MSG_MOTION_JOG,
    MSG_MOTION_HOME,
    MSG_MOTION_STOP,
    MSG_MOTION_ESTOP,
    MSG_MOTION_RESET,
    MSG_MOTION_SET_DRV_ENABLE,
    MSG_STATUS_MOTION,
    MSG_STATUS_TMC,
    build_jog_payload,
    build_home_payload,
    build_bcode_payload,
    build_drv_enable_payload,
)

log = logging.getLogger(__name__)

# 페이로드 struct 포맷 (ipc_protocol.h 와 반드시 일치해야 한다)
_MOTION_STATUS_FMT  = "<B4f4fHHBB"    # state + pos[4] + vel[4] + curr_step + total + axis_mask + drv_enabled
_MOTION_STATUS_SIZE = struct.calcsize(_MOTION_STATUS_FMT)
_TMC_STATUS_FMT     = "<4I4H4H4i"     # drv_status[4] + sg_result[4] + cs_actual[4] + xactual[4]
_TMC_STATUS_SIZE    = struct.calcsize(_TMC_STATUS_FMT)


class MotorService:
    """
    상위 레벨 모터 제어 인터페이스.

    모든 메서드는 async 이며 FastAPI 라우트 핸들러에서 바로 호출해도 안전하다.
    """

    def __init__(self, ipc: IpcClient, spidev_backend=None) -> None:
        self._ipc = ipc
        # 선택적 spidev 백엔드 — M7 IPC 가 mock 모드이고 SpidevMotorBackend 가
        # 주어지면, 모터 명령이 존재하지 않는 M7 로 IPC 를 보내는 대신 실제
        # Veyron 1×2A 벤치에서 실행된다. FastAPI 서버가 EVK 테스트 벤치의
        # 모터를 직접 구동할 수 있게 해 준다.
        self._spi_backend = spidev_backend
        # 축 ID → spidev cs (cs=0 LIFT, 1 BEND, 2 FEED). ROTATE 는 벤치에 없다.
        self._axis_to_cs = {
            int(AxisId.LIFT):   0,
            int(AxisId.BEND):   1,
            int(AxisId.FEED):   2,
            int(AxisId.ROTATE): None,
        }
        # 길게 누르는 조그: 벤치 비동기 태스크는 한 번에 하나만
        import asyncio as _asyncio
        self._asyncio = _asyncio
        self._bench_jog_task: Optional[_asyncio.Task] = None
        # _run_motion 의 "선점 후 시작" 임계 구역을 직렬화한다 — 이게 없으면
        # 동시에 들어온 두 HTTP 모션이 아무것도 안 도는 사이에 둘 다
        # jog_stop() 을 통과해서 공유 PWM 위에 pulse_step 코루틴을 둘 띄운다.
        self._motion_lock = _asyncio.Lock()
        # 절대 이동은 서로 선점하지 않고 큐에 쌓인다: 벤치는 STEP 라인을
        # 공유하므로 두 축이 동시에 돌 수는 없지만, 세 축에서 "Move To" 를
        # 눌렀다면 세 개가 차례로 다 실행되어야지 뒤에 누른 것이 앞의 것을
        # 취소해서는 안 된다.
        self._queue_lock = _asyncio.Lock()
        self._queue_depth: int = 0
        # stop()/estop() 이 증가시킨다. 세대(generation) 가 낡은 큐 대기 이동은
        # 중단 이후에 시작되지 않고 폐기된다.
        self._motion_generation: int = 0
        # 끈적이는(sticky) E-STOP 플래그 — enable_drivers/reset 이 지울 때까지
        # True 로 남는다. 조그 태스크가 끝나는 순간 IDLE 로 튀지 않고 대시보드가
        # 계속 ESTOP 을 보여줄 수 있게 하기 위해서다. 이게 없으면 취소가
        # 진행 중인 동안 _bench_status 가 JOGGING 을 돌려주어 진행 바가 계속
        # 움직였다.
        self._bench_estop_active: bool = False
        self._last_fault_clear: dict | None = None
        # 리밋 스위치 호밍 상태(벤치): 호밍 시퀀스가 도는 동안 세우는 플래그
        # (상태 표시가 HOMING 이 된다), 서버 기동 이후 호밍이 끝난 축 집합,
        # 마지막 호밍 실패 사유(GET /api/motor/limits 로 노출된다).
        self._bench_homing: bool = False
        self._homed_axes: set[int] = set()
        self._home_error: Optional[str] = None
        # 축별 스텝/단위 캘리브레이션. main.py 가 MotorService 생성 이후에
        # 연결할 수 있도록 set_calibration() 으로 나중에 주입한다.
        self._calibration = None  # type: ignore[assignment]
        # 마지막 TMC 상태를 캐시해 두어 폴링 사이에도 모터 상태에 포함시킨다
        self._last_tmc: Optional[bytes] = None

        # 벤치 B-code 실행기 상태. M7 이 없는 벤치에서 execute_bcode 가
        # 서버 내부 루프로 시퀀스를 실행할 때의 진행 상황이다.
        self._bcode_task: Optional[object] = None
        self._bcode = {"current": 0, "total": 0, "error": None,
                       "aborted": False}

    @property
    def has_bench(self) -> bool:
        return self._spi_backend is not None

    def set_calibration(self, cal) -> None:
        """축 스텝/단위 변환에 쓰는 CalibrationService 를 주입한다."""
        self._calibration = cal

    def set_motion_profiles(self, profiles) -> None:
        """MotionProfileService(축별 accel/decel/shape)를 주입한다."""
        self._motion_profiles = profiles

    def _profile_for(self, axis: int) -> dict | None:
        """`axis` 에 대해 백엔드가 받을 램프 프로파일.

        프로파일은 accel/decel 을 물리 단위(mm/s² 또는 deg/s²)로 저장하지만
        램프 엔진은 STEP 주파수 기울기(Hz/s)를 소비한다. 속도에 쓰는 것과
        같은 축별 steps_per_unit 캘리브레이션으로 여기서 변환하고, 벤치 PWM
        경로가 검증된 범위로 클램프한다.
        """
        mp = getattr(self, "_motion_profiles", None)
        if mp is None:
            return None
        p = mp.get(axis)
        cal = self._calibration
        spu = cal.steps_per_unit(axis) if cal else 200.0
        out = {"start_hz": p["start_hz"], "shape": p["shape"]}
        for phys, hz in (("accel", "accel_hz_s"), ("decel", "decel_hz_s")):
            # [200, 40000] Hz/s 클램프가 램프 엔진 직전의 마지막 관문이다.
            # 고운 축은 프로파일 상한 200 units/s² 에 닿기 훨씬 전에 이
            # 천장에 부딪힌다: 200 mm/s² x 200 steps/mm = 정확히 40000 Hz/s
            # 이므로 LIFT 에서는 프로파일 범위의 꼭대기가 곧 램프 범위의
            # 꼭대기이고, 더 요구해도 아무것도 달라지지 않는다. BEND
            # (23 steps/deg)에서는 같은 200 deg/s² 가 4600 Hz/s 밖에 안 되어
            # 여유가 많다.
            out[hz] = int(max(200, min(40000, float(p[phys]) * spu)))
        return out

    async def _run_motion(self, coro) -> None:
        """벤치 모션을 배타적으로 실행한다(마지막 명령이 이긴다).

        예전에는 move/move_to/jog(distance) 가 상호 배제 없이 pulse_step 을
        인라인으로 await 했다 — 하나가 도는 중에 두 번째 요청이 들어오면 공유
        PWM 위에서 pulse_step 코루틴 두 개가 뒤섞이며 위치 카운터가 엉켰다
        (실제로 카운터가 약 1회전 어긋난 상태로 남아 다음 절대 이동이 한 바퀴를
        통째로 돌았다). 이제 모든 모션은 단일 태스크 슬롯을 지난다: 이미 도는
        것(조그, 이전 이동)은 감속 + 정확한 스텝 정산과 함께 먼저 취소되고,
        STOP/E-STOP 도 이동을 취소할 수 있다.
        """
        async with self._motion_lock:       # 선점과 시작을 원자적으로
            # nudge=False: 내부 선점은 즉시 취소되어야 한다 — 최소 넛지 유예는
            # 운전자가 버튼에서 손을 뗀 경우를 위한 것이다.
            await self.jog_stop(nudge=False)
            task = self._asyncio.create_task(coro)
            self._bench_jog_task = task
        try:
            await task
        except self._asyncio.CancelledError:
            # 더 새로운 명령(또는 STOP)에 선점된 경우: 모션은 깨끗한 감속으로
            # 끝났다 — "우리 자신" 이 취소당한 게 아니라면 삼킨다.
            if not task.cancelled():
                raise
        finally:
            if self._bench_jog_task is task:
                self._bench_jog_task = None

    def _max_speed_for(self, axis: int) -> float:
        """축별 머신 속도 상한(프로파일의 max_speed).

        GRBL $110-112 방식의 명령 시점 클램프다: 운전자용 기본값인 jog_speed
        와는 구분되는 머신 한계이며, API 를 직접 호출해도 넘을 수 없다.
        저장된 프로파일을 읽으며, _profile_for 가 만드는 백엔드용 dict
        (램프 파라미터만 담긴다)를 읽지 않는다.
        """
        mp = getattr(self, "_motion_profiles", None)
        if mp is None:
            return 40.0
        return float(mp.get(axis).get("max_speed", 40.0))

    def _ensure_not_estop(self, action: str) -> None:
        """하드 게이트 — 벤치 E-STOP 이 걸려 있는 동안 모션 명령을 거부한다.

        2026-05-09 사고: ESTOP 표시가 켜진 상태에서도 대시보드의 조그 버튼이
        살아 있어 운전자가 한 번 누르는 것만으로 모터를 구동할 수 있었다.
        백엔드가 최후의 방어선이다 — 프론트엔드에서 비활성화를 해 두더라도
        모든 직접 API 호출은 여기에 걸려서, enable_drivers()/reset() 이
        플래그를 지울 때까지 거부되어야 한다.
        """
        if self._bench_estop_active:
            raise RuntimeError(
                f"E-STOP active — refusing {action}. Press RESET E-STOP "
                f"(or POST /api/motor/reset) before issuing motion commands."
            )

    async def jog_start(
        self,
        axis: int,
        direction: int,
        speed: float = 1000.0,
        continuous: bool = False,
    ) -> dict:
        """벤치 회전을 시작한다.

        두 가지 모드:
          - continuous=False (기본값, 길게 누르는 ◀ / ▶ 버튼이 사용):
            안전 폴백으로 5 초 길이. 프론트엔드는 pointerup 에서 jog_stop 을
            보내야 하며, 5 초 상한은 정지 요청이 유실된 경우를 대비한 것이다.
          - continuous=True (한 번 클릭하는 ◀◀ / ▶▶ 버튼이 사용):
            60 초 길이. 사용자가 해당 행의 STOP 버튼(jog_stop 호출)을 누를
            때까지 계속 돈다. 60 초는 정지를 잊었을 때의 무인 구동 시간을
            제한한다.
        """
        self._ensure_not_estop("jog_start")
        if not self.has_bench:
            payload = build_jog_payload(axis, direction, speed, 0.0)
            await self._ipc.send_recv(MSG_MOTION_JOG, payload)
            return {"status": "jog_started", "bench": False}

        await self.jog_stop()

        cs = self._axis_to_cs.get(axis)
        if cs is None:
            raise ValueError(f"Axis {axis} is not present on the bench")

        # 속도는 축 고유의 사용자 단위다(FEED/LIFT 는 mm/s, BEND/ROTATE 는
        # deg/s). CalibrationService 가 스텝 레이트로 변환하므로, 운전자가
        # "10 mm/s" 를 입력하면 모터 마이크로스텝이나 리드스크류 사양과
        # 무관하게 캘리브레이션된 속도로 와이어가 나간다.
        # 벤치 하드 상한은 PWM 8000 Hz. DRVCTRL 1/16 마이크로스텝 + DEDGE
        # (PWM 사이클당 마이크로스텝 2개)에서 이는 16,000 µsteps/s =
        # 5 rev/s = 모터축 300 RPM 이다. 이 상한을 올리려면 벤치 검증
        # (PWM 패드 무결성 + 스톨 거동)을 한 번 거쳐야 한다.
        cal = self._calibration
        steps_per_unit = cal.steps_per_unit(axis) if cal else 200.0
        speed_clamped = min(abs(speed), cal.speed_limit(axis) if cal else 40.0,
                            self._max_speed_for(axis))
        freq = int(speed_clamped * steps_per_unit)
        freq = max(200, min(freq, 8000))
        max_duration_s = 60 if continuous else 5
        steps = freq * max_duration_s
        dir_sign = 1 if direction >= 0 else -1
        log.info("jog_start axis=%d cs=%d freq=%dHz dir=%+d (max %ds, continuous=%s)",
                 axis, cs, freq, dir_sign, max_duration_s, continuous)
        self._bench_jog_task = self._asyncio.create_task(
            self._spi_backend.pulse_step(cs, steps, freq, dir_sign,
                                         profile=self._profile_for(axis))
        )
        return {
            "status": "jog_started",
            "bench": True,
            "axis": axis,
            "freq_hz": freq,
            "continuous": continuous,
            "max_duration_s": max_duration_s,
        }

    async def jog_stop(self, nudge: bool = True) -> dict:
        """현재 벤치 조그를 정지한다(길게 누르기에서 손을 뗀 경우).

        백그라운드 pulse_step 태스크를 취소한다. 그 태스크의 finally 블록이
        PWM 을 끄고 활성 칩을 침묵시킨다. 이중 안전장치로 백엔드의
        pwm_disable 도 호출해 출력이 깨끗한지 보장한다. 여기서 모든 칩을
        침묵시키지는 않는다(pulse_step 의 finally 가 건드리는 것은 돌던 축
        하나뿐이다) — 빠르게 연타할 때의 데드타임을 줄이기 위해서다.
        """
        # 태스크 참조를 스냅샷해 둔다: 아래의 유예 대기들은 이벤트 루프에
        # 양보하는데, 그 사이 동시에 들어온 jog_stop(빠른 더블탭 — 두 번째
        # jog_start 도 jog_stop 을 호출한다)이 태스크를 취소하고
        # self._bench_jog_task 를 None 으로 만들 수 있다. await 이후에 속성을
        # 다시 읽었더니 'NoneType' has no attribute 'done' 이 났다.
        task = self._bench_jog_task
        if task is not None and not task.done():
            # 최소 넛지 보장: 아주 짧게 톡 누르면 모션 태스크가 아직 준비
            # 단계(약 100 ms: DIR 셋업 + 예열된 칩 init)에 있을 때 손을 떼게
            # 되는데, 여기서 그냥 취소하면 사용자는 코일이 물리는 소리를
            # 듣거나 봤는데도 스텝이 0개가 된다. 아직 STEP 이 하나도 나가지
            # 않았고 호밍 중이 아니라면, PWM 이 시작될 때까지 기다린 뒤 짧은
            # 유예를 더 줘서 모든 탭이 축을 몇 스텝이라도 밀도록 한다.
            be = self._spi_backend
            if (nudge and be is not None and not self._bench_homing
                    and not getattr(be, "_pwm_active", True)
                    and not getattr(be, "_pwm_killed", False)):
                for _ in range(40):            # ≤ 0.4 s 상한
                    if getattr(be, "_pwm_active", False) or task.done():
                        break
                    await self._asyncio.sleep(0.01)
                if getattr(be, "_pwm_active", False) and not task.done():
                    await self._asyncio.sleep(0.05)   # 바닥 주파수에서 약 10 스텝
            task.cancel()
            try:
                await task
            except (self._asyncio.CancelledError, Exception):
                pass
        # 그 사이 더 새로운 모션 태스크가 자리를 차지하지 않았을 때만 비운다.
        if self._bench_jog_task is task:
            self._bench_jog_task = None
        if self.has_bench:
            try:
                await self._spi_backend._pwm_disable()
            except Exception:
                pass
        return {"status": "jog_stopped"}

    async def _bench_pulse(
        self,
        axis: int,
        distance: float,
        speed: float,
    ) -> None:
        """move/jog 의 (distance, speed) 를 벤치 pulse_step 호출로 변환한다.

        보수적인 매핑(벤치에서 단위는 응용이 정한다):
          거리 1 unit = 마이크로스텝 200개  (200 step/rev 기준 약 1회전)
          속도 1 unit = 스텝 레이트 1 Hz    (프론트엔드는 보통 1000 같은 큰
                                            값을 보내며 Hz 로 취급한다)
        안전 클램프:
          - 거리 |abs| ≤ 50 units (마이크로스텝 10,000개 이하)
          - 주파수     ≤ 4000 Hz (단일 축 벤치 안전값)
          - 지속시간   ≤ 10 s
        """
        cs = self._axis_to_cs.get(axis)
        if cs is None:
            raise ValueError(f"Axis {axis} is not present on the bench")

        # ---- 프론트엔드가 보낸 값에 대한 안전 클램프 ----
        # 프론트엔드는 큰 값(speed=1000 등)을 보낼 수 있다. 속도를 Hz 로
        # 직접 취급하되 안전한 상한을 건다.
        cal = self._calibration
        steps_per_unit = cal.steps_per_unit(axis) if cal else 200.0
        dist_limit = cal.distance_limit(axis) if cal else 50.0
        speed_lim = cal.speed_limit(axis) if cal else 40.0
        clamped_distance = max(-dist_limit, min(dist_limit, distance))
        # 반올림이어야 한다: 절단(int)이면 정수 스텝 지령이 부동소수점 표현
        # (4.0 -> 3.9999…) 때문에 한 스텝 모자라게 나가고, 모든 착지가 짧은
        # 쪽으로 편향된다 — 등간격 스냅 이송에서 4/3/5 스텝이 섞이던 원인.
        steps = max(1, int(round(abs(clamped_distance) * steps_per_unit)))
        speed_clamped = min(abs(speed), speed_lim, self._max_speed_for(axis))
        freq = int(speed_clamped * steps_per_unit)
        freq = max(200, min(freq, 8000))
        # 지속시간을 10 s 로 제한
        if steps / freq > 10.0:
            steps = freq * 10
        direction = 1 if distance >= 0 else -1
        log.info(
            "bench jog axis=%d cs=%d steps=%d freq=%dHz dir=%+d (req dist=%.3f speed=%.3f)",
            axis, cs, steps, freq, direction, distance, speed,
        )
        await self._spi_backend.pulse_step(cs, steps, freq, direction,
                                           profile=self._profile_for(axis))

    # ------------------------------------------------------------------
    # 상태
    # ------------------------------------------------------------------

    async def get_status(self) -> MotorStatusResponse:
        """현재 모터 위치·속도·상태를 조회한다.

        벤치 모드: SpidevMotorBackend.positions(pulse_step 으로 실제 구동된
        마이크로스텝 카운트)에서 상태를 합성하며 IPC 를 전혀 쓰지 않는다.
        운영 모드: IPC 로 M7 에 질의한다.
        """
        if self.has_bench:
            return self._bench_status()
        resp = await self._ipc.send_recv(MSG_STATUS_MOTION)
        return self._parse_motion_status(resp.payload)

    def _bench_status(self) -> MotorStatusResponse:
        """spidev 백엔드가 추적하는 위치로 MotorStatusResponse 를 만든다.

        spidev cs (0/1/2) = LIFT/BEND/FEED. AxisId 로 역매핑:
          cs=0 → AxisId.LIFT (3)
          cs=1 → AxisId.BEND (1)
          cs=2 → AxisId.FEED (0)
        AxisId.ROTATE (2) 는 벤치에 없다(건너뛴다).
        """
        bench_pos = getattr(self._spi_backend, "positions", {})
        # cs → AxisId 정수
        cs_to_axis = {0: int(AxisId.LIFT), 1: int(AxisId.BEND), 2: int(AxisId.FEED)}
        axes = []
        axis_mask = 0
        signals_fn = getattr(self._spi_backend, "get_axis_signals", None)
        for cs, axis_int in cs_to_axis.items():
            pos_steps = bench_pos.get(cs, 0)
            # 마이크로스텝을 표시 단위로 되돌린다(_bench_pulse 의 역: 200 step = 1 unit)
            spu = (self._calibration.steps_per_unit(axis_int)
                   if self._calibration else 200.0)
            pos_units = pos_steps / spu
            sig_dict = signals_fn(cs) if callable(signals_fn) else None
            axes.append(AxisStatus(
                axis=AxisId(axis_int),
                position=pos_units,
                velocity=0.0,
                drv_status=0,
                sg_result=(sig_dict.get("sg_value") or 0) if sig_dict else 0,
                # 상수가 아니라 PSU 캡까지 적용한 실효 코일 전류.
                # 예전에는 이 필드가 무조건 19 를 읽어서, PSU 프리셋이 얼마로
                # 클램프했든 축이 안전 천장에서 도는 것처럼 보였다.
                cs_actual=int(self._spi_backend.effective_cs(cs))
                          if hasattr(self._spi_backend, "effective_cs") else 0,
                signals=AxisSignals(**sig_dict) if sig_dict else None,
            ))
            axis_mask |= (1 << axis_int)
        # 축 id 순 정렬(프론트엔드의 0..3 순서와 일치)
        axes.sort(key=lambda a: int(a.axis))
        # 대시보드의 "State: IDLE/JOGGING" 표시가 벤치의 실제 동작과 맞도록
        # state 필드에 실제 모션을 반영한다.
        # ESTOP 은 끈적이며 JOGGING 을 이긴다 — 운전자가 E-STOP 을 누른 뒤에는
        # enable_drivers()/reset() 으로 조건이 명시적으로 해제될 때까지
        # 대시보드가 계속 그것을 보여줘야 한다. 취소된 조그 태스크만 보면
        # state 가 IDLE 로 떨어져 버리기 때문이다.
        bench_jog_active = (
            self._bench_jog_task is not None and not self._bench_jog_task.done()
        )
        # B-code 실행기가 도는 동안은 개별 move 사이의 짧은 유휴가 있어도
        # RUNNING 으로 보고한다 — /api/bending 의 진행 폴링과 대시보드가
        # 시퀀스 단위로 상태를 읽기 때문이다.
        bcode_active = (self._bcode_task is not None
                        and not self._bcode_task.done())
        if self._bench_estop_active:
            state = MotionState.ESTOP
        elif bcode_active:
            # 실행기 내부의 개별 move 가 조그 태스크로 돌더라도 시퀀스가
            # 살아 있는 동안은 RUNNING 이 이긴다 — JOGGING 으로 떨어지면
            # /api/bending 의 진행 폴링(state==RUNNING)이 중간에 끊긴다.
            state = MotionState.RUNNING
        elif bench_jog_active:
            state = MotionState.HOMING if self._bench_homing else MotionState.JOGGING
        else:
            state = MotionState.IDLE
        return MotorStatusResponse(
            state=state,
            axes=axes,
            current_step=int(self._bcode["current"]),
            total_steps=int(self._bcode["total"]) if bcode_active
                        or self._bcode["current"] else 0,
            axis_mask=axis_mask,
            driver_enabled=True,
        )

    def _parse_motion_status(self, payload: bytes) -> MotorStatusResponse:
        if len(payload) < _MOTION_STATUS_SIZE:
            log.warning("Motion status payload too short: %d bytes", len(payload))
            # 안전한 기본값 반환
            return MotorStatusResponse(
                state=MotionState.IDLE,
                axes=[],
                current_step=0,
                total_steps=0,
                axis_mask=0,
                driver_enabled=False,
            )

        raw = struct.unpack_from(_MOTION_STATUS_FMT, payload)
        state          = raw[0]
        positions      = list(raw[1:5])
        velocities     = list(raw[5:9])
        curr_step      = raw[9]
        total_steps    = raw[10]
        axis_mask      = raw[11]
        driver_enabled = bool(raw[12])

        # 뒤에 TMC 상태가 붙어 있으면(연결된 페이로드) 함께 파싱한다
        tmc_raw = None
        if len(payload) >= _MOTION_STATUS_SIZE + _TMC_STATUS_SIZE:
            tmc_raw = struct.unpack_from(_TMC_STATUS_FMT, payload, _MOTION_STATUS_SIZE)

        axes = []
        for i in range(4):
            if not (axis_mask & (1 << i)):
                continue
            axes.append(AxisStatus(
                axis=AxisId(i),
                position=positions[i],
                velocity=velocities[i],
                drv_status=tmc_raw[i] if tmc_raw else 0,
                sg_result=tmc_raw[4 + i] if tmc_raw else 0,
                cs_actual=tmc_raw[8 + i] if tmc_raw else 0,
            ))

        return MotorStatusResponse(
            state=MotionState(state),
            axes=axes,
            current_step=curr_step,
            total_steps=total_steps,
            axis_mask=axis_mask,
            driver_enabled=driver_enabled,
        )

    # ------------------------------------------------------------------
    # 명령
    # ------------------------------------------------------------------

    async def move(self, axis: int, distance: float, speed: float) -> MotorStatusResponse:
        """
        한 축을 주어진 속도로 주어진 거리만큼 이동시킨다.

        - 벤치 모드(spidev 백엔드): Veyron 보드에서 pulse_step 직접 실행.
        - 운영 모드(M7 IPC): 단일 스텝 B-code → M7 궤적 관리자.
        """
        self._ensure_not_estop("move")
        if self.has_bench:
            await self._run_motion(self._bench_pulse(axis, distance, speed))
            return await self.get_status()

        # IPC 경로 (M7 운영)
        L_mm    = distance if axis == AxisId.FEED else 0.0
        beta    = distance if axis == AxisId.ROTATE else 0.0
        theta   = distance if axis == AxisId.BEND else 0.0

        payload = build_bcode_payload(
            steps=[(L_mm, beta, theta)],
            material_id=0,          # SS_304 기본값
            wire_diameter_mm=0.457,
        )
        await self._ipc.send_recv(MSG_MOTION_EXECUTE_BCODE, payload)
        return await self.get_status()

    async def jog(
        self, axis: int, direction: int, speed: float, distance: float = 0.0
    ) -> MotorStatusResponse:
        """한 축을 연속으로, 또는 고정 거리만큼 조그한다.

        벤치 모드: distance=0 이면 1회전(200 스텝)을 기본으로 하고 부호는
        `direction` 인자를 따른다. 운영 모드: MSG_MOTION_JOG 를 보낸다.
        """
        self._ensure_not_estop("jog")
        if self.has_bench:
            d = distance if distance != 0.0 else 1.0
            d *= (1 if direction >= 0 else -1)
            await self._run_motion(self._bench_pulse(axis, d, speed if speed > 0 else 10.0))
            return await self.get_status()

        payload = build_jog_payload(axis, direction, speed, distance)
        await self._ipc.send_recv(MSG_MOTION_JOG, payload)
        return await self.get_status()

    async def set_zero(self, axis: int, value: float = 0.0) -> MotorStatusResponse:
        """현재의 물리적 위치를 `value`(사용자 단위)로 정의한다.

        벤치의 영점/datum 설정이다: 운전자가 축을 알려진 기준(기계적 스토퍼,
        표시, 앞으로 달릴 리밋 스위치)까지 조그한 뒤 위치 카운터를 `value`
        (보통 0)라고 선언한다. 카운터는 영속되므로 서버를 재시작해도 남는다.
        상태 표시와 동일한 steps-per-unit 규약을 쓴다. M7 호밍이 들어오기
        전까지는 벤치 전용이다.
        """
        if not self.has_bench:
            raise RuntimeError("set_zero is only available in bench mode")
        cs = self._axis_to_cs.get(int(axis))
        if cs is None:
            raise ValueError(f"Axis {axis} is not present on the bench")
        # _bench_status 와 같은 변환(축별 캘리브레이션).
        spu = (self._calibration.steps_per_unit(int(axis))
               if self._calibration else 200.0)
        self._spi_backend.positions[cs] = int(round(value * spu))
        save = getattr(self._spi_backend, "_save_state", None)
        if callable(save):
            save()
        log.info("set_zero: axis=%d (cs=%d) position counter := %.3f units",
                 axis, cs, value)
        return await self.get_status()

    async def home(self, axis_mask: int = 0) -> MotorStatusResponse:
        """지정한 축들에 대해 리밋 스위치 호밍을 수행한다.

        벤치: 리밋 스위치가 달린 요청 축(LIFT 와 BEND — PM-L25 포토
        인터럽터)을 백그라운드 모션 태스크로 차례차례 호밍한다. 호출은
        state=HOMING 으로 즉시 반환되고, 진행 상황은 /ws/motor 로 흐르며
        완료/실패는 GET /api/motor/limits 로 확인한다. jog/stop(또는 E-STOP)이
        호밍을 취소한다.
        axis_mask=0 → 호밍 가능한 축 전부(비트 의미: 0x02=BEND, 0x08=LIFT).
        """
        self._ensure_not_estop("home")
        if not self.has_bench:
            payload = build_home_payload(axis_mask)
            await self._ipc.send_recv(MSG_MOTION_HOME, payload)
            return await self.get_status()

        from ..config import get_settings
        cfg = get_settings()
        plan: list[tuple[int, int, int]] = []   # (axis, cs, direction)
        for axis, cs, dir_ in (
            (int(AxisId.LIFT), 0, cfg.home_dir_lift),
            (int(AxisId.BEND), 1, cfg.home_dir_bend),
        ):
            if axis_mask and not (axis_mask >> axis) & 1:
                continue
            if self._spi_backend.limit_active(cs) is None:
                log.warning("home: axis=%d has no limit switch — skipped", axis)
                continue
            plan.append((axis, cs, 1 if dir_ >= 0 else -1))
        if not plan:
            raise RuntimeError(
                "no homable axes — limit switches are fitted on LIFT and "
                "BEND only (check axis_mask / gpio_limit_* config)")

        await self.jog_stop()
        self._home_error = None
        self._bench_homing = True
        self._bench_jog_task = self._asyncio.create_task(self._home_sequence(plan))
        return await self.get_status()

    async def _home_sequence(self, plan: list[tuple[int, int, int]]) -> None:
        """계획된 축들을 한 번에 하나씩 호밍한다(STEP 라인이 하나뿐이다)."""
        from ..config import get_settings
        cfg = get_settings()
        cal = self._calibration
        try:
            for axis, cs, direction in plan:
                spu = cal.steps_per_unit(axis) if cal else 200.0
                rotary = axis == int(AxisId.BEND)   # 연속 회전, 1회전당 창 1개
                if rotary:
                    seek_speed = cfg.home_seek_speed_bend
                elif axis == int(AxisId.LIFT):
                    seek_speed = cfg.home_seek_speed_lift
                else:
                    seek_speed = cfg.home_seek_speed
                seek_hz = int(seek_speed * spu)
                latch_hz = int(cfg.home_latch_speed * spu)
                backoff = int(cfg.home_backoff * spu)
                # 이동 하드 상한: 스위치는 축의 캘리브레이션된 이동거리(×1.1)
                # 안에서 반드시 나타나야 한다 — 센서가 죽었으면 하드 스토퍼를
                # 갈아 대는 대신 중단한다.
                dist_lim = cal.distance_limit(axis) if cal else 50.0
                max_travel = int(dist_lim * 1.1 * spu)
                if rotary:
                    # 1회전 + 여유면 언제나 창을 지나간다 — 단방향 탐색,
                    # 방향 전환 없음.
                    search_range = int(cfg.home_rev_bend * spu)
                    preprobe = 0
                elif axis == int(AxisId.LIFT):
                    # 스위치가 상단 끝에 있다: 스트로크 전체를 한 번 훑으면
                    # 항상 찾을 수 있고, 그 너머에는 아무것도 없다.
                    search_range = int(cfg.home_search_range_lift * spu)
                    preprobe = 0
                else:
                    search_range = int(cfg.home_search_range * spu)
                    preprobe = int(cfg.home_preprobe * spu)
                reduced = int(cfg.home_reduced_cs) if rotary else 0
                log.info("homing axis=%d cs=%d dir=%+d rotary=%s seek=%dHz "
                         "latch=%dHz backoff=%d search=%d max_travel=%d "
                         "preprobe=%d reduced_cs=%d", axis, cs, direction,
                         rotary, seek_hz, latch_hz, backoff, search_range,
                         max_travel, preprobe, reduced)
                await self._spi_backend.home_axis(
                    cs, direction, seek_hz, latch_hz, backoff,
                    timeout_s=cfg.home_timeout_s,
                    park_steps=int(cfg.home_park * spu),
                    max_travel_steps=max_travel,
                    search_range_steps=search_range,
                    reduced_cs=reduced,
                    rotary=rotary,
                    preprobe_steps=preprobe,
                    stall_abort=bool(cfg.home_stall_abort) and not rotary)
                self._homed_axes.add(axis)
                # 위치 카운터와 함께 "datum 이 실제로 잡혔다" 는 사실도
                # 영속시켜서 재시작 후에도 둘 다 유지되게 한다.
                hp = getattr(self._spi_backend, "homed_persist", None)
                if hp is not None:
                    hp.add(axis)
                    save = getattr(self._spi_backend, "_save_state", None)
                    if callable(save):
                        save()
                log.info("homing axis=%d complete", axis)
        except self._asyncio.CancelledError:
            self._home_error = "homing cancelled"
            log.warning("homing sequence cancelled")
            raise
        except Exception as exc:
            self._home_error = str(exc)
            log.error("homing failed: %s", exc)
        finally:
            self._bench_homing = False

    def limit_status(self) -> dict:
        """리밋 스위치 실시간 상태 + 호밍 진행 정보(벤치)."""
        limits: dict[int, bool] = {}
        if self.has_bench:
            for axis, cs in ((int(AxisId.LIFT), 0), (int(AxisId.BEND), 1),
                             (int(AxisId.FEED), 2)):
                st = self._spi_backend.limit_active(cs)
                if st is not None:
                    limits[axis] = st
        homed = set(self._homed_axes)
        homed |= set(getattr(self._spi_backend, "homed_persist", set()) or set())
        return {
            "queued": self._queue_depth,
            "limits": limits,
            "homed": sorted(homed),
            "homing": self._bench_homing,
            "error": self._home_error,
        }

    # ------------------------------------------------------------------
    # 보호 / 유지 토크 설정 (벤치)
    # ------------------------------------------------------------------
    # 유지(hold)가 가능한 축. ROTATE 는 이 벤치에 장착되어 있지 않다.
    _HOLDABLE = (int(AxisId.FEED), int(AxisId.BEND), int(AxisId.LIFT))

    def get_protection(self) -> dict:
        """런타임 모션 보호 설정.

        `axes` 가 축별 유지 토크를 담는다. `hold_enabled` / `hold_cs` 는
        예전 클라이언트가 계속 동작하도록 남겨 둔 LIFT 형태의 별칭이다.
        """
        be = self._spi_backend
        held = getattr(be, "hold_axes", set()) or set()
        axes = {}
        for axis in self._HOLDABLE:
            cs = self._axis_to_cs.get(axis)
            if cs is None:
                continue
            axes[axis] = {
                "hold_enabled": cs in held,
                "hold_cs": int(be.hold_cs_for(cs)) if hasattr(be, "hold_cs_for")
                           else int(getattr(be, "hold_cs", 0)),
                # 축에 설정된 값과, PSU 캡을 거친 뒤 실제로 적용될 값.
                # 공급이 허용하는 것보다 크게 요청하면 둘이 달라지는데,
                # 이를 감추면 클램프된 축이 제대로 설정된 축처럼 보인다.
                "run_cs": int(be.run_cs_map.get(cs, SGCSCONF_DEFAULT & 0x1F))
                          if hasattr(be, "run_cs_map")
                          else (SGCSCONF_DEFAULT & 0x1F),
                "run_cs_effective": int(be.run_cs_for(cs))
                                    if hasattr(be, "run_cs_for") else 0,
            }
        lift_cs = self._axis_to_cs.get(int(AxisId.LIFT))
        return {
            "limit_stop": bool(getattr(be, "limit_guard", False)),
            "cs_cap": int(getattr(be, "_cs_scale_cap", 0)),
            "cs_max": SAFETY_CS_MAX,
            "axes": axes,
            # 레거시 별칭 (LIFT)
            "hold_enabled": lift_cs in held,
            "hold_cs": axes.get(int(AxisId.LIFT), {}).get(
                "hold_cs", int(getattr(be, "hold_cs", 0))),
        }

    async def set_protection(self, limit_stop=None, hold_enabled=None,
                             hold_cs=None, axes=None) -> dict:
        """보호 설정을 갱신한다.

        `axes` 는 축별 맵 {axis: {hold_enabled?, hold_cs?}} 이며, 이것 없이
        온 `hold_enabled`/`hold_cs` 는 LIFT 에 적용된다(레거시 형태).
        유지 관련 변경은 벤치가 유휴 상태이면 즉시 반영된다.
        """
        if not self.has_bench:
            raise RuntimeError("protection settings are bench-only")
        be = self._spi_backend
        if limit_stop is not None:
            be.limit_guard = bool(limit_stop)

        # 모든 요청을 축별 맵 하나로 정규화한다.
        patch: dict[int, dict] = {}
        if axes:
            for k, v in axes.items():
                patch[int(k)] = dict(v or {})
        if hold_enabled is not None or hold_cs is not None:
            lift = patch.setdefault(int(AxisId.LIFT), {})
            if hold_enabled is not None:
                lift.setdefault("hold_enabled", bool(hold_enabled))
            if hold_cs is not None:
                lift.setdefault("hold_cs", int(hold_cs))

        touched: list[int] = []
        for axis, v in patch.items():
            if axis not in self._HOLDABLE:
                raise ValueError(f"axis {axis} cannot be held on this bench")
            cs = self._axis_to_cs.get(axis)
            if cs is None:
                continue
            if "hold_cs" in v and v["hold_cs"] is not None:
                be.hold_cs_map[cs] = max(1, min(int(v["hold_cs"]), 19))
            if "run_cs" in v and v["run_cs"] is not None:
                # run_cs_for() 에서 살아 있는 PSU 캡으로 다시 클램프된다.
                # 여기서도 클램프해 두면, 상태 파일을 손으로 고치더라도
                # 저장된 값이 천장 위에 올라앉는 일이 없다.
                be.run_cs_map[cs] = max(1, min(int(v["run_cs"]), 19))
            if "hold_enabled" in v and v["hold_enabled"] is not None:
                if v["hold_enabled"]:
                    be.hold_axes = set(be.hold_axes) | {cs}
                else:
                    be.hold_axes = set(be.hold_axes) - {cs}
            touched.append(cs)

        idle = self._bench_jog_task is None or self._bench_jog_task.done()
        if touched and idle and not self._bench_estop_active:
            for cs in touched:
                try:
                    if cs in be.hold_axes:
                        await be._hold_chip(cs)
                    else:
                        await be._silence_chip(cs)
                except Exception as exc:
                    log.warning("hold re-apply cs=%d failed: %s", cs, exc)
        save = getattr(be, "_save_state", None)
        if callable(save):
            save()
        log.info("protection updated: %s", self.get_protection())
        return self.get_protection()

    # ------------------------------------------------------------------
    # StallGuard2 임계값 (센서리스 부하 / 스톨 측정)
    # ------------------------------------------------------------------
    async def set_axis_enable(self, axis: int, on: bool,
                             exclusive: bool = False) -> dict:
        """한 축의 코일을 여자하거나 해제한다.

        /api/motor/enable 과 /disable 은 이 벤치가 돌리지 않는 M7 로
        디스패치되므로, 지금까지는 개별 칩의 초퍼를 제어할 방법이 없었다 —
        유일한 레버가 유지 토크였는데 그것은 목적이 다른 별개의 기능이다.

        `exclusive` 는 다른 축을 먼저 전부 침묵시킨다. 수동 작업의 안전한
        기본값이다: 세 드라이버가 STEP 라인 하나를 공유하므로, 펄스가 올 때
        여자되어 있는 축은 명령한 축과 함께 움직인다.
        """
        if not self.has_bench:
            raise RuntimeError("per-axis enable is bench-only")
        if axis not in self._HOLDABLE:
            raise ValueError(f"axis {axis} is not on this bench")
        be = self._spi_backend
        cs = self._axis_to_cs[axis]

        idle = self._bench_jog_task is None or self._bench_jog_task.done()
        if not idle:
            raise RuntimeError("axis is moving — stop it first")
        if self._bench_estop_active:
            raise RuntimeError("E-STOP active — reset before energizing")

        if on and exclusive:
            for other in self._HOLDABLE:
                if other == axis:
                    continue
                ocs = self._axis_to_cs.get(other)
                if ocs is not None:
                    try:
                        await be._silence_chip(ocs)
                    except Exception as exc:
                        log.warning("silence cs=%d failed: %s", ocs, exc)

        try:
            if on:
                await be._hold_chip(cs)
            else:
                await be._silence_chip(cs)
        except Exception as exc:
            raise RuntimeError(f"axis {axis} enable failed: {exc}") from exc

        log.info("axis %d coils %s%s", axis, "ON" if on else "off",
                 " (exclusive)" if on and exclusive else "")
        return self.axis_enable_state()

    def axis_enable_state(self) -> dict:
        """현재 초퍼가 켜져 있는 축이 어디인지."""
        be = self._spi_backend
        out = {}
        for axis in self._HOLDABLE:
            cs = self._axis_to_cs.get(axis)
            if cs is None:
                continue
            sig = be.get_axis_signals(cs) if hasattr(be, "get_axis_signals") else {}
            out[axis] = {
                "enabled": bool(sig.get("en")),
                "holding": cs in getattr(be, "hold_axes", set()),
            }
        return {"axes": out}

    def get_stallguard(self) -> dict:
        """축별 StallGuard 임계값 + 실시간 SG_RESULT."""
        be = self._spi_backend
        axes = {}
        for axis in self._HOLDABLE:
            cs = self._axis_to_cs.get(axis)
            if cs is None:
                continue
            sig = be.get_axis_signals(cs) if hasattr(be, "get_axis_signals") else {}
            axes[axis] = {
                "sgt": int(be.sgt_for(cs)) if hasattr(be, "sgt_for") else 63,
                "sg_result": int(be._last_sg_value.get(cs, 0))
                             if hasattr(be, "_last_sg_value") else 0,
                "stall": bool(sig.get("sg")),
                "energized": bool(sig.get("en")),
            }
        rail = getattr(be, "rail_suspect", None)
        out = {"axes": axes, "filter": bool(getattr(be, "sg_filter", True))}
        if callable(rail) and rail():
            out["warning"] = (
                "All driver boards report the same fault word with no "
                "standstill flag — the shared 12 V motor supply is the "
                "likely cause, not the individual axes. Measure VMot at a "
                "driver board terminal before driving anything."
            )
        return out

    async def set_stallguard(self, axis: int | None = None, sgt: int | None = None,
                             filter: bool | None = None) -> dict:
        """한 축의 StallGuard 임계값(또는 SFILT 플래그)을 설정한다.

        SGT 는 부호 있는 7비트 값이며 낮을수록 민감하다. 전원 투입 기본값인
        +63 은 사실상 스톨 보고를 꺼 놓은 상태이고, 튜닝하지 않은 축에서
        SG_RESULT 가 평평하게 나오는 이유다. 벤치가 유휴이면 즉시 칩에
        반영되고, 그렇지 않더라도 이후의 모든 모션에서 적용된다.
        """
        if not self.has_bench:
            raise RuntimeError("StallGuard tuning is bench-only")
        be = self._spi_backend
        if filter is not None:
            be.sg_filter = bool(filter)
        if axis is not None and sgt is not None:
            if axis not in self._HOLDABLE:
                raise ValueError(f"axis {axis} is not on this bench")
            if not -64 <= int(sgt) <= 63:
                raise ValueError("sgt must be within -64..63")
            cs = self._axis_to_cs[axis]
            be.sgt_map[cs] = int(sgt)
            save = getattr(be, "_save_state", None)
            if callable(save):
                save()
            idle = self._bench_jog_task is None or self._bench_jog_task.done()
            if idle and not self._bench_estop_active:
                try:
                    # 재초기화가 새 임계값으로 SGCSCONF 를 쓴다. 유지 중인
                    # 축은 계속 유지하고, 나머지는 이전처럼 침묵시킨다.
                    if cs in getattr(be, "hold_axes", set()):
                        await be._hold_chip(cs)
                    else:
                        await be._init_chip(cs)
                        await be._silence_chip(cs)
                except Exception as exc:
                    log.warning("SGT apply cs=%d failed: %s", cs, exc)
        log.info("stallguard updated: %s", self.get_stallguard())
        return self.get_stallguard()

    def microstep_status(self) -> dict:
        """축별 분주비 + 그에 따른 분해능/속도 상한 (UI 표시용)."""
        if not self.has_bench or not hasattr(self._spi_backend, "usteps_for"):
            raise RuntimeError("microstep control is bench-only")
        out = {}
        for axis, cs in self._axis_to_cs.items():
            if cs is None:
                continue
            spu = (self._calibration.steps_per_unit(axis)
                   if self._calibration else 200.0)
            snap_axes = getattr(self._spi_backend, "snap_axes", None) or set()
            out[str(axis)] = {
                "microsteps": self._spi_backend.usteps_for(cs),
                "steps_per_unit": spu,
                "mm_per_step": (1.0 / spu) if spu else None,
                "speed_limit": (self._calibration.speed_limit(axis)
                                if self._calibration else None),
                "uniform": int(axis) in snap_axes,
            }
        return out

    async def set_microstep(self, axis: int, microsteps: int | None = None,
                            uniform: bool | None = None) -> dict:
        """한 축의 분주비·완전 균일 모드를 바꾼다.

        microsteps: 카운터·캘리브레이션이 같은 배율로 따라간다. 모션 중
        변경은 거부(칩 재초기화가 진행 중인 펄스와 경합). 속도 상한은
        steps_per_unit 유도값이라 자동 추종.
        uniform: move_to 지령 거리를 정수 스텝으로 스냅하는 축별 정책 —
        모션과 경합하지 않으므로 언제든 바꿀 수 있고, 영속화된다.
        """
        if not self.has_bench or not hasattr(self._spi_backend, "set_axis_microstep"):
            raise RuntimeError("microstep control is bench-only")
        cs = self._axis_to_cs.get(int(axis))
        if cs is None:
            raise ValueError(f"Axis {axis} is not present on the bench")
        if microsteps is not None:
            st = await self.get_status()
            if any(a.velocity for a in st.axes) or self._queue_depth:
                raise RuntimeError("cannot change microstep while motion is active")
            ratio = self._spi_backend.set_axis_microstep(cs, int(microsteps))
            if ratio != 1.0 and self._calibration:
                self._calibration.update(
                    int(axis), self._calibration.steps_per_unit(int(axis)) * ratio)
        if uniform is not None:
            snap = set(getattr(self._spi_backend, "snap_axes", None) or set())
            (snap.add if uniform else snap.discard)(int(axis))
            self._spi_backend.snap_axes = snap
            if hasattr(self._spi_backend, "_save_state_soon"):
                self._spi_backend._save_state_soon()
        return self.microstep_status()

    async def move_to(self, axis: int, position: float, speed: float) -> MotorStatusResponse:
        """절대 이동: 현재 카운터에서 `position`(사용자 단위)까지 이동한다.
        /move 엔드포인트는 상대 이동이라서, UI 의 'Move To Position' 에는
        이런 델타 형태가 필요하다."""
        self._ensure_not_estop("move_to")
        if not self.has_bench:
            raise RuntimeError("move_to is bench-only")
        cs = self._axis_to_cs.get(int(axis))
        if cs is None:
            raise ValueError(f"Axis {axis} is not present on the bench")
        spu = (self._calibration.steps_per_unit(int(axis))
               if self._calibration else 200.0)
        # 이미 실행 중인 절대 이동 뒤에 줄을 선다(STEP 라인 공유 = 한 번에
        # 한 축). 조그 / STOP / E-STOP 은 이 락을 잡지 않으므로 여전히 즉시
        # 선점한다.
        generation = self._motion_generation
        self._queue_depth += 1
        try:
            await self._queue_lock.acquire()
        finally:
            self._queue_depth -= 1
        try:
            if generation != self._motion_generation:
                log.info("move_to axis=%d dropped — stop/E-STOP while queued",
                         axis)
                return await self.get_status()
            self._ensure_not_estop("move_to")
            snap_axes = getattr(self._spi_backend, "snap_axes", None) or set()
            if int(axis) in snap_axes:
                # '완전 균일' 축: 지령 거리(현재 위치 기준)를 가장 가까운
                # 정수 스텝으로 스냅한다. 같은 거리를 반복 지령하는
                # 클라이언트는 매회 정확히 같은 스텝 수를 얻는다(카운터가
                # 항상 스텝 격자 위라 델타가 같으면 반올림도 같다). 절대
                # 좌표 래더를 보내는 클라이언트에는 절대 그리드(±0.5 스텝
                # 추종)로 자연 퇴화하며 폭주하지 않는다. mm 그리드와 스텝
                # 그리드는 pi 때문에 통약 불가능하므로, 이 모드는 '평균
                # 정확' 대신 '등간격'을 택한 것이다 — 실이동 위치가 응답에
                # 그대로 보고된다.
                current = self._spi_backend.positions.get(cs, 0) / spu
                whole = round((float(position) - current) * spu)
                position = current + whole / spu
            return await self._move_to_locked(axis, position, speed, cs, spu)
        finally:
            self._queue_lock.release()

    async def _move_to_locked(self, axis: int, position: float, speed: float,
                              cs: int, spu: float) -> MotorStatusResponse:
        """실제 절대 이동 본체. 호출자가 큐 락을 쥐고 있다.

        벤치 펄스 한 번은 두 번 제한된다 — 축별 거리 상한과 10 s 지속시간
        상한 — 그래서 예전에는 긴 절대 이동이 오류도 없이 중간에 멈췄다
        (230 mm LIFT 이동이 100 mm 에서 끝났다). 그래서 절대 이동은 목표에
        도달할 때까지 여러 조각으로 나눠 실행하며, 매 회차마다 카운터를 다시
        읽으므로 잘린 조각은 그냥 다음 조각을 하나 더 받는다."""
        # 착지 허용 오차: 모터 2 스텝. 이보다 더 잘게 램프로 쫓아가 봐야 보정
        # 회차마다 자기 램프가 붙으므로 서브스텝 잔차를 다른 잔차로 바꾸는
        # 것일 뿐이다.
        tol = max(2.0 / spu, 0.01)
        prev_gap = None
        for _ in range(40):
            current = self._spi_backend.positions.get(cs, 0) / spu
            gap = float(position) - current
            if abs(gap) < tol:
                # 허용오차 안이라도 온전한 스텝이 남아 있으면 그만큼은 낸다.
                # 이게 없으면 2 스텝 미만의 절대 이동 지령(63.662 steps/unit
                # 의 FEED 에서 0.03 mm 급 미세 이송)이 회차마다 통째로
                # 무시된다 — 2026-09-01 obtest feed.step 실측에서 0.03 mm
                # x20 중 13회가 무동작이었다. 램프를 다시 쫓는 게 아니라
                # 잔차의 정수 스텝을 한 번 내보내고 끝나므로, 위 주석의
                # "램프 잔차 교환" 문제는 그대로 피한다. 서브스텝 잔차
                # (<1 step)는 여전히 남는다 — 스텝은 쪼갤 수 없다.
                if int(abs(gap) * spu + 1e-6) >= 1:
                    await self._run_motion(
                        self._bench_pulse(int(axis), gap, speed))
                break
            if prev_gap is not None and abs(gap) > abs(prev_gap) * 0.7:
                # 이번 회차가 거리를 거의 줄이지 못했다 — 막혔거나, 스톨했거나,
                # 이미 분해능 바닥에 닿은 것이다. 제자리에서 도는 대신 멈춘다.
                log.info("move_to axis=%d settled at %.3f (target %.3f, "
                         "residue %.3f)", axis, current, position, gap)
                break
            prev_gap = gap
            await self._run_motion(self._bench_pulse(int(axis), gap, speed))
        return await self.get_status()

    async def stop(self) -> MotorStatusResponse:
        """제어된 감속 정지. 큐에 대기 중인 절대 이동도 함께 폐기한다.

        벤치 모드: 백엔드 pulse_step 의 마무리 단계가 침묵 + PWM 비활성을
        처리한다.
        """
        self._motion_generation += 1     # 큐에 있던 이동들이 낡은 것이 된다
        if self.has_bench:
            await self.jog_stop(nudge=False)
            return await self.get_status()
        await self._ipc.send_recv(MSG_MOTION_STOP)
        return await self.get_status()

    async def estop(self) -> MotorStatusResponse:
        """소프트웨어 E-STOP — 즉시 정지.

        벤치: 지금 어느 축이 돌고 있든 상관없이 PWM 을 끄고 모든 칩을 동기적으로
        침묵시킨다. 안전상 중요한 경로다.
        운영: 하드웨어 E-STOP 이 M7 GPIO ISR + DRV_ENN 으로 병행 동작한다.
        """
        self._motion_generation += 1     # 큐에 있던 이동들이 낡은 것이 된다
        if self.has_bench:
            # 1) PWM 을 죽이고 칩을 즉시 침묵시킨다. 2단계에서 예외가 나더라도
            #    모터가 기계적으로 안전하도록 코일을 먼저 끈다.
            try:
                # kill=True 는 PWM off 를 래치한다 — 진행 중인 램프 틱이
                # 취소가 도착하기 전에 STEP 을 다시 켜지 못하게 해야 한다.
                await self._spi_backend._pwm_disable(kill=True)
            except Exception as exc:
                log.warning("E-STOP PWM disable failed: %s", exc)
            for cs in (0, 1, 2):
                try:
                    await self._spi_backend._silence_chip(cs)
                except Exception as exc:
                    log.warning("E-STOP silence cs=%d failed: %s", cs, exc)
            # 2) 진행 중인 조그 태스크를 취소한다. 이게 없으면 모터가 전기적으로
            #    멈춘 뒤에도 pulse_step_multi 루프가 self._spi_backend.positions
            #    를 계속 증가시켜, 대시보드의 진행 바/위치 표시가 E-STOP 이후에
            #    흘러간다. 사용자가 정확히 이 현상을 봤다: 모터는 섰는데 UI 는
            #    계속 세고 있었다.
            if self._bench_jog_task is not None and not self._bench_jog_task.done():
                self._bench_jog_task.cancel()
                try:
                    await self._bench_jog_task
                except (self._asyncio.CancelledError, Exception):
                    pass
            self._bench_jog_task = None
            # 3) 끈적이는 ESTOP 을 세워, 운전자가 조건을 해제했음을
            #    enable_drivers() / reset() 로 확인해 줄 때까지 _bench_status 가
            #    MotionState.ESTOP 을 보고하도록 한다.
            self._bench_estop_active = True
            log.warning("E-STOP triggered on bench: all axes silenced + jog task cancelled")
            return await self.get_status()
        await self._ipc.send_recv(MSG_MOTION_ESTOP)
        return await self.get_status()

    async def enable_drivers(self, axis_mask: int = 0) -> MotorStatusResponse:
        """
        TMC260C-PA 의 DRV_ENN 을 어서트한다(코일 여자).

        연결이 끊겼다 복구된 뒤의 표준 절차다: 드라이버가 다시 위치를 유지한다.
        M7 핸들러가 최종 권한을 가지며, 여기서는 IPC 를 보내기만 한다.

        끈적이는 벤치 E-STOP 플래그도 함께 지운다 — 드라이버를 다시 켜는 것이
        곧 E-STOP 조건이 해소되었다는 운전자의 명시적 확인이기 때문이다.

        중요 — 여기서 모든 cs 에 _init_chip 을 하면 안 된다. PWM4 는 세
        TMC260C-PA 칩이 공유한다: 대상이 아닌 축이 함께 스텝하지 않는 이유가
        바로 그 축들이 침묵 상태이기 때문이다. 예전 버전은 SG LED 를 끄려고
        cs=0/1/2 에 _init_chip 을 돌렸는데, 그 바람에 모든 초퍼가 ON 이 되어
        다음 조그가 세 모터를 동시에 구동했다(2026-05-09 사고). E-STOP 이후
        칩은 침묵 상태로 두고, 다음 jog_start 가 자기 축만 재초기화한다.
        침묵 중인 축의 SG LED 는 그 축이 비활성이라는 정상 표시이며, 그 축을
        조그하는 순간 꺼진다.
        """
        if self.has_bench:
            self._bench_estop_active = False
            # 래치된 드라이버 폴트를 실제로 해제한다. 이전에는 E-STOP 플래그만
            # 내려서, 래치된 S2G 가 있으면 누군가 전원을 껐다 켤 때까지 벤치가
            # 모든 이동을 거부했다.
            clear = getattr(self._spi_backend, "clear_driver_faults", None)
            if callable(clear):
                try:
                    self._last_fault_clear = await clear()
                except Exception as exc:
                    log.warning("driver fault clear failed: %s", exc)
            return await self.get_status()
        payload = build_drv_enable_payload(True, axis_mask)
        await self._ipc.send_recv(MSG_MOTION_SET_DRV_ENABLE, payload)
        return await self.get_status()

    async def disable_drivers(self, axis_mask: int = 0) -> MotorStatusResponse:
        """
        DRV_ENN 을 해제해 TMC260C-PA 코일의 전원을 뺀다.

        마스크에 든 축 중 하나라도 움직이는 중이면 M7 이 거부한다. 호출자는
        먼저 `stop()` 한 뒤 `disable_drivers()` 를 불러야 한다.
        """
        payload = build_drv_enable_payload(False, axis_mask)
        await self._ipc.send_recv(MSG_MOTION_SET_DRV_ENABLE, payload)
        return await self.get_status()

    async def reset(self) -> MotorStatusResponse:
        """모터 폴트 상태를 리셋하고 벤치 E-STOP 래치를 해제한다.

        enable_drivers 와 같은 제약이 걸린다: 여기서 모든 cs 에 _init_chip 을
        하면 안 된다 — 세 칩의 초퍼가 전부 ON 이 되어 다음 조그가 전 축을
        구동하게 된다(PWM 공유). 칩은 침묵 상태로 두고, 다음 jog_start 가
        대상 축만 재초기화한다.
        """
        if self.has_bench:
            self._bench_estop_active = False
            # 리셋은 폴트에서 빠져나오는 공식 경로이므로 실제로 폴트를 지워야
            # 한다. 이전에는 E-STOP 플래그만 내려서, 래치된 단락 감지가 남아
            # 있으면 누군가 직접 가서 모터 전원을 끊을 때까지 모든 이동이
            # 거부되었다.
            clear = getattr(self._spi_backend, "clear_driver_faults", None)
            if callable(clear):
                try:
                    self._last_fault_clear = await clear()
                except Exception as exc:
                    log.warning("driver fault clear failed: %s", exc)
            return await self.get_status()
        # TODO: M7 펌웨어가 축별 리셋을 지원하면 axis_mask 페이로드를 추가할 것
        await self._ipc.send_recv(MSG_MOTION_RESET)
        return await self.get_status()

    # ------------------------------------------------------------------
    # 벤딩 시퀀스 (BendingService 에서 위임)
    # ------------------------------------------------------------------

    async def execute_bcode(
        self,
        steps: list[tuple[float, float, float]],
        material_id: int,
        wire_diameter_mm: float,
    ) -> None:
        """
        전체 B-code 시퀀스를 실행한다.

        벤치 모드: 서버 내부 루프가 스텝별로 FEED 이송 -> BEND 굽힘/복귀를
        move_to(절대 스텝 그리드)로 실행한다 — M7 이 없는 벤치에서 실제
        와이어를 굽는 유일한 경로다. 운영 모드: M7 로 IPC 디스패치한다.

        두 경로 모두 디스패치까지만 블로킹한다. 호출자는
        /api/bending/status 를 폴링해 진행/완료를 확인한다. STOP 은 현재
        이동을 감속 정지시키고 남은 스텝을 폐기하며, E-STOP/폴트는 즉시
        중단으로 기록된다.
        """
        if self.has_bench:
            if self._bcode_task is not None and not self._bcode_task.done():
                raise RuntimeError("bcode sequence already running")
            self._bcode = {"current": 0, "total": len(steps), "error": None,
                           "aborted": False}
            self._bcode_task = self._asyncio.create_task(
                self._bench_bcode_run(list(steps)))
            log.info("B-code bench executor started: %d steps, material=%d",
                     len(steps), material_id)
            return
        payload = build_bcode_payload(steps, material_id, wire_diameter_mm)
        await self._ipc.send_recv(MSG_MOTION_EXECUTE_BCODE, payload)
        log.info("B-code sequence dispatched: %d steps, material=%d", len(steps), material_id)

    # B-code 벤치 실행 속도(사용자 단위/s). 보수적 기본값 — 필요하면 축별
    # 모션 프로파일(가감속)은 move_to 경로가 이미 적용하므로 여기서는 순항
    # 속도만 정한다.
    _BCODE_FEED_SPEED = 10.0    # mm/s
    _BCODE_BEND_SPEED = 45.0    # deg/s

    async def _bench_bcode_run(
        self, steps: list[tuple[float, float, float]]
    ) -> None:
        """B-code 시퀀스의 벤치 실행 본체.

        스텝마다: FEED 를 L_mm 만큼 절대 그리드로 전진 -> (beta 는 ROTATE
        미장착이라 경고 후 생략) -> BEND 를 시작 각도 + theta 로 굽혔다가
        시작 각도로 복귀. 모든 이동이 move_to 를 지나므로 정밀 경로·리밋
        가드·E-STOP 게이트를 그대로 상속한다.

        중단 규칙: STOP(_motion_generation 증가)이 오면 현재 이동은 감속
        정산으로 끝나고 다음 스텝 경계에서 시퀀스를 접는다(aborted=True).
        E-STOP/드라이버 폴트는 예외로 도착해 error 로 기록된다.
        """
        gen = self._motion_generation
        feed_axis, bend_axis = int(AxisId.FEED), int(AxisId.BEND)
        try:
            st = await self.get_status()
            pos = {int(a.axis): float(a.position) for a in st.axes}
            feed_target = pos.get(feed_axis, 0.0)
            bend_home = pos.get(bend_axis, 0.0)
            for i, (L, beta, theta) in enumerate(steps, 1):
                if gen != self._motion_generation:
                    self._bcode["aborted"] = True
                    log.info("bcode aborted by stop at step %d/%d",
                             i, len(steps))
                    return
                if beta:
                    # ROTATE(axis 2)는 벤치에 없다 — 각도 회전은 생략하고
                    # 남은 공정은 계속한다. 운영기(M7)에서는 실제 회전한다.
                    log.warning("bcode step %d: beta=%.1f deg skipped — "
                                "ROTATE not fitted on bench", i, beta)
                if L > 0:
                    feed_target += float(L)
                    await self.move_to(feed_axis, feed_target,
                                       self._BCODE_FEED_SPEED)
                if gen != self._motion_generation:
                    self._bcode["aborted"] = True
                    return
                if theta:
                    await self.move_to(bend_axis, bend_home + float(theta),
                                       self._BCODE_BEND_SPEED)
                    if gen != self._motion_generation:
                        # 굽힌 채로 멈추지 않는다 — 복귀는 마저 한다. STOP
                        # 직후라 generation 이 바뀌어 있으므로 새 세대로
                        # 이동해야 큐에서 버려지지 않는다.
                        gen = self._motion_generation
                        self._bcode["aborted"] = True
                        await self.move_to(bend_axis, bend_home,
                                           self._BCODE_BEND_SPEED)
                        return
                    await self.move_to(bend_axis, bend_home,
                                       self._BCODE_BEND_SPEED)
                self._bcode["current"] = i
            log.info("bcode bench sequence complete: %d steps", len(steps))
        except Exception as exc:
            self._bcode["error"] = str(exc)
            log.error("bcode bench sequence failed at step %d/%d: %s",
                      self._bcode["current"] + 1, len(steps), exc)
