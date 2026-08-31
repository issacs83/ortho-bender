"""
routers/motor.py — /api/motor/* REST 엔드포인트.

모든 응답은 표준 봉투 형식을 쓴다: {"success": bool, "data": {...}}.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..models.schemas import (
    ApiResponse,
    MotionState,
    MotorHomeRequest,
    MotorZeroRequest,
    MotorJogRequest,
    MotorMoveRequest,
    MotorResetRequest,
    err,
    ok,
)
from ..services.motor_service import MotorService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/motor", tags=["motor"])


def _motor_service(request: Request) -> MotorService:
    return request.app.state.motor_service


def _calibration_service(request: Request):
    return getattr(request.app.state, "calibration_service", None)


from pydantic import BaseModel as _BaseModel


class CalibrationUpdate(_BaseModel):
    axis: int
    steps_per_unit: float


# ---------------------------------------------------------------------------
# GET /api/motor/calibration  +  POST /api/motor/calibration
# 튜닝 노브 0(steps_per_unit) 의 조회/변경 창구.
# ---------------------------------------------------------------------------

@router.get("/calibration", response_model=ApiResponse)
async def get_calibration(svc=Depends(_calibration_service)) -> ApiResponse:
    """현재 축별 steps_per_unit 맵 + 축별 상한을 반환한다."""
    if svc is None:
        return err("calibration not available", "NO_BENCH")
    return ok(svc.all())


@router.post("/calibration", response_model=ApiResponse)
async def update_calibration(
    body: CalibrationUpdate, svc=Depends(_calibration_service)
) -> ApiResponse:
    """한 축의 steps_per_unit 을 설정한다."""
    if svc is None:
        return err("calibration not available", "NO_BENCH")
    try:
        svc.update(body.axis, body.steps_per_unit)
        return ok(svc.all())
    except ValueError as exc:
        return err(str(exc), "INVALID_CALIBRATION")


# ---------------------------------------------------------------------------
# GET /api/motor/status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=ApiResponse)
async def get_motor_status(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """활성 축 전체의 현재 위치·속도·상태를 반환한다."""
    try:
        status = await svc.get_status()
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor status query failed: %s", exc)
        return err(str(exc), "MOTOR_STATUS_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/move
# ---------------------------------------------------------------------------

@router.post("/move", response_model=ApiResponse)
async def motor_move(
    body: MotorMoveRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """한 축을 지정한 속도로 지정한 거리만큼 이동시킨다(상대 이동)."""
    try:
        status = await svc.move(body.axis, body.distance, body.speed)
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor move failed axis=%s dist=%s: %s", body.axis, body.distance, exc)
        return err(str(exc), "MOTOR_MOVE_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/jog
# ---------------------------------------------------------------------------

@router.post("/jog", response_model=ApiResponse)
async def motor_jog(
    body: MotorJogRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """한 축을 연속으로, 또는 고정 거리만큼 조그한다."""
    try:
        status = await svc.jog(body.axis, body.direction, body.speed, body.distance)
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor jog failed: %s", exc)
        return err(str(exc), "MOTOR_JOG_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/jog/start  +  POST /api/motor/jog/stop  (길게 누르는 조그)
# ---------------------------------------------------------------------------

@router.post("/jog/start", response_model=ApiResponse)
async def motor_jog_start(
    body: MotorJogRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """벤치 연속 조그를 시작한다.

    두 가지 방식을 지원한다:
      - 길게 누르기 (기본값, body.continuous=False): pointerdown → 시작,
        pointerup → /jog/stop. 5 초 안전 폴백.
      - 한 번 클릭해 연속 주행 (body.continuous=True): 클릭 한 번 → 주행,
        수동 STOP 버튼 → /jog/stop. 60 초 안전 폴백.
    """
    try:
        result = await svc.jog_start(
            body.axis, body.direction, body.speed, continuous=body.continuous
        )
        return ok(result)
    except Exception as exc:
        log.error("Motor jog/start failed: %s", exc)
        return err(str(exc), "MOTOR_JOG_START_ERROR")


@router.post("/jog/stop", response_model=ApiResponse)
async def motor_jog_stop(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """현재 벤치 조그를 정지한다(길게 누르기에서 손을 뗀 경우)."""
    try:
        result = await svc.jog_stop()
        return ok(result)
    except Exception as exc:
        log.error("Motor jog/stop failed: %s", exc)
        return err(str(exc), "MOTOR_JOG_STOP_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/home
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field


class MotionProfileUpdate(BaseModel):
    """축별 모션 프로파일 부분 업데이트 — 생략한 필드는 기존 값을 유지한다.

    모르는 필드는 거부한다(422). 0.3.0 이전의 `accel_hz_s`/`decel_hz_s`
    이름을 계속 보내는 클라이언트가 "성공했지만 아무 효과 없음" 이 되지 않고
    시끄럽게 실패하도록 하기 위해서다.
    """
    model_config = {"extra": "forbid"}
    jog_speed: float | None = Field(None, gt=0, le=360,
                                    description="Default jog rate (mm/s or deg/s)")
    max_speed: float | None = Field(None, gt=0, le=360,
                                    description="Machine velocity limit — all motion "
                                                "commands are clamped to this "
                                                "(GRBL $110-112 analog)")
    step_size: float | None = Field(None, gt=0, le=360,
                                    description="Incremental jog distance (mm or deg)")
    start_hz: int | None = Field(None, ge=50, le=2000,
                                 description="Ramp floor frequency (Hz)")
    accel: float | None = Field(None, ge=1, le=200,
                                description="Acceleration in physical units "
                                            "(mm/s² or deg/s²; converted to STEP "
                                            "slew via axis calibration)")
    decel: float | None = Field(None, ge=1, le=200,
                                description="Deceleration for stop/finish ramps "
                                            "(mm/s² or deg/s²)")
    shape: str | None = Field(None, pattern="^(linear|scurve)$",
                              description="Velocity profile: trapezoidal 'linear' "
                                          "or jerk-limited 'scurve'")


def _profiles(request: Request):
    return request.app.state.motion_profiles


@router.get("/profiles", response_model=ApiResponse)
async def get_motion_profiles(request: Request) -> ApiResponse:
    """축별 모션 프로파일(조그 기본값 + 가감속 형상).

    accel/decel 은 물리 단위(mm/s² 또는 deg/s²)이며 명령 시점에 축
    캘리브레이션으로 STEP 기울기로 변환된다. S-curve 는 최대 기울기가 설정된
    accel 과 같아지는 smoothstep 주파수 스케줄을 쓰므로, shape 를 바꿔도
    설정한 가속도를 넘는 일은 없다. 벤치는 이 프로파일을 모든 jog/move 램프에
    적용하며, 정지와 이동 종료 시의 감속 램프에도 그대로 쓴다.
    """
    return ok({"profiles": _profiles(request).all()})


@router.put("/profiles/{axis}", response_model=ApiResponse)
async def update_motion_profile(
    axis: int, body: MotionProfileUpdate, request: Request,
) -> ApiResponse:
    """한 축의 모션 프로파일을 갱신한다(부분 업데이트, 보드에 영속)."""
    try:
        updated = _profiles(request).update(
            axis, body.model_dump(exclude_none=True))
        return ok({"axis": axis, "profile": updated})
    except ValueError as exc:
        return err(str(exc), "MOTOR_PROFILE_ERROR")


@router.post("/zero", response_model=ApiResponse)
async def motor_set_zero(
    body: MotorZeroRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """영점(datum) 설정 — 현재의 물리적 위치를 선언한다.

    축을 알려진 기준(기계적 스토퍼, 표시, 또는 배선이 끝난 리밋 스위치)까지
    조그한 뒤 이 API 를 호출하면 위치 카운터가 `value`(기본 0)로 정의된다.
    이때 모터는 움직이지 않으며, 카운터는 재시작 후에도 유지된다. 벤치의 두
    리밋 스위치를 이용한 호밍도 전원과 배선이 되면 이 위에서 동작한다.
    """
    try:
        status = await svc.set_zero(int(body.axis), body.value)
        return ok(status.model_dump())
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), "MOTOR_ZERO_ERROR")


@router.get("/limits", response_model=ApiResponse)
async def motor_limits(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """리밋 스위치 실시간 상태 + 호밍 진행 정보.

    응답: `limits` 는 축 id → 스위치 눌림 여부 맵이며 스위치가 달린 축만
    나온다(1=BEND, 3=LIFT). `homed` 는 서버 기동 이후 호밍이 끝난 축 목록,
    `homing` 은 호밍 시퀀스가 도는 동안 True, `error` 는 마지막 호밍 실패
    사유(없으면 null)다. 스위치 상태는 /ws/motor 의 축별 `signals.limit`
    로도 스트리밍된다.
    """
    try:
        return ok(svc.limit_status())
    except Exception as exc:
        log.error("Motor limits query failed: %s", exc)
        return err(str(exc), "MOTOR_LIMITS_ERROR")


class AxisHoldUpdate(BaseModel):
    """한 축의 토크 설정.

    튜닝 노브 2(전류/토크): run_cs 는 이동 중, hold_cs 는 정지 중 코일 전류다.
    둘 다 PSU 프리셋 캡과 SAFETY_CS_MAX(19)로 다시 클램프된다.
    """
    model_config = {"extra": "forbid"}
    hold_enabled: bool | None = None
    hold_cs: int | None = Field(
        None, ge=1, le=19,
        description="Idle holding current scale (1-19).")
    run_cs: int | None = Field(
        None, ge=1, le=19,
        description="Coil current while this axis MOVES (1-19). Still "
                    "clamped by the PSU preset cap: ask for more than the "
                    "supply allows and run_cs_effective reports what you "
                    "actually get. 19 is the ceiling -- two boards were "
                    "destroyed at CS=31.")


class ProtectionUpdate(BaseModel):
    """보호/유지 설정의 부분 업데이트(생략한 항목은 그대로 유지)."""
    model_config = {"extra": "forbid"}
    limit_stop: bool | None = Field(
        None, description="Stop an axis that ENTERS its limit window during "
                          "normal motion (edge-triggered; leaving the window "
                          "from a parked-at-home start is never blocked)")
    hold_enabled: bool | None = Field(
        None, description="Idle holding current on LIFT (gravity axis) — "
                          "prevents sinking; audible chopper hiss while held")
    hold_cs: int | None = Field(
        None, ge=1, le=19,
        description="Holding torque current scale (1-19, PSU cap still "
                    "applies). Lower = quieter + less holding torque")
    axes: dict[int, AxisHoldUpdate] | None = Field(
        None,
        description="Per-axis holding torque, e.g. "
                    "{\"0\": {\"hold_enabled\": true, \"hold_cs\": 12}}. "
                    "Axis ids: 0=FEED, 1=BEND, 3=LIFT (ROTATE not fitted)")


class MoveToRequest(BaseModel):
    model_config = {"extra": "forbid"}
    axis: int = Field(ge=0, le=3)
    position: float = Field(ge=-100000, le=100000,
                            description="Absolute target (user units)")
    speed: float = Field(gt=0, le=360)


@router.get("/protection", response_model=ApiResponse)
async def get_protection(svc: MotorService = Depends(_motor_service)) -> ApiResponse:
    """모션 보호 + 유지 토크 설정(limit_stop / hold_enabled / hold_cs).

    응답의 run_cs 는 설정값, run_cs_effective 는 PSU 캡까지 적용한 실제
    적용값이다 — 둘이 다르면 클램프된 것이지 설정이 안 된 것이 아니다.
    """
    try:
        return ok(svc.get_protection())
    except Exception as exc:
        return err(str(exc), "MOTOR_PROTECTION_ERROR")


@router.put("/protection", response_model=ApiResponse)
async def update_protection(
    body: ProtectionUpdate,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """보호 설정을 갱신한다. 유지(hold) 관련 변경은 벤치가 유휴 상태이면
    즉시 반영된다."""
    try:
        result = await svc.set_protection(
            limit_stop=body.limit_stop,
            hold_enabled=body.hold_enabled,
            hold_cs=body.hold_cs,
            axes={k: v.model_dump(exclude_none=True)
                  for k, v in (body.axes or {}).items()} or None)
        return ok(result)
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), "MOTOR_PROTECTION_ERROR")


class StallGuardUpdate(BaseModel):
    """StallGuard2 튜닝. sgt 가 낮을수록 민감하며, 전원 투입 기본값인 +63 은
    사실상 스톨 보고를 꺼 놓은 상태다."""
    model_config = {"extra": "forbid"}
    axis: int | None = Field(None, ge=0, le=3)
    sgt: int | None = Field(None, ge=-64, le=63)
    filter: bool | None = Field(
        None, description="SFILT — average over 4 electrical periods "
                          "(smoother, 4x slower response)")


@router.get("/stallguard", response_model=ApiResponse)
async def get_stallguard(svc: MotorService = Depends(_motor_service)) -> ApiResponse:
    """축별 StallGuard 임계값, 실시간 SG_RESULT, 스톨 플래그."""
    try:
        return ok(svc.get_stallguard())
    except Exception as exc:
        return err(str(exc), "MOTOR_SG_ERROR")


@router.put("/stallguard", response_model=ApiResponse)
async def update_stallguard(
    body: StallGuardUpdate,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """한 축의 StallGuard 임계값을 설정한다(보드에 영속)."""
    try:
        return ok(await svc.set_stallguard(axis=body.axis, sgt=body.sgt,
                                           filter=body.filter))
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), "MOTOR_SG_ERROR")


@router.post("/move_to", response_model=ApiResponse)
async def motor_move_to(
    body: MoveToRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """`position`(사용자 단위)으로 가는 절대 이동. POST /move 는 상대 이동
    (`distance` 만큼 이동)이고, 이 엔드포인트는 현재 카운터에서의 차이를
    계산한다 — UI 의 'Move To Position' 이 뜻하는 동작이다."""
    try:
        status = await svc.move_to(body.axis, body.position, body.speed)
        return ok(status.model_dump())
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), "MOTOR_MOVE_ERROR")
    except Exception as exc:
        log.error("move_to failed axis=%s pos=%s: %s", body.axis, body.position, exc)
        return err(str(exc), "MOTOR_MOVE_ERROR")


@router.post("/home", response_model=ApiResponse)
async def motor_home(
    body: MotorHomeRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """리밋 스위치 호밍(GRBL 방식의 2패스).

    스위치가 있는 축만 호밍한다(0x02=BEND, 0x08=LIFT. axis_mask=0 이면
    호밍 가능한 축 전부): 빠른 탐색 → 후퇴 → 느린 래치 → 스위치 위치를
    datum 0 으로 → 풀오프. 호출은 state=HOMING 으로 즉시 반환되므로 완료는
    /ws/motor 로, 결과는 GET /limits 로 확인한다. POST /jog/stop 또는
    E-STOP 으로 취소된다.
    """
    try:
        status = await svc.home(body.axis_mask)
        return ok(status.model_dump())
    except RuntimeError as exc:
        return err(str(exc), "MOTOR_HOME_ERROR")
    except Exception as exc:
        log.error("Motor home failed (mask=0x%02x): %s", body.axis_mask, exc)
        return err(str(exc), "MOTOR_HOME_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/stop
# ---------------------------------------------------------------------------

@router.post("/stop", response_model=ApiResponse)
async def motor_stop(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """제어된 감속 정지(소프트 스톱)."""
    try:
        status = await svc.stop()
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor stop failed: %s", exc)
        return err(str(exc), "MOTOR_STOP_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/estop
# ---------------------------------------------------------------------------

@router.post("/estop", response_model=ApiResponse)
async def motor_estop(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """
    소프트웨어 E-STOP — IPC 를 통한 즉시 정지(SW 경로).
    하드웨어 E-STOP 경로는 M7 의 GPIO ISR + DRV_ENN 이 독립적으로 처리한다.
    """
    try:
        status = await svc.estop()
        log.warning("SW E-STOP triggered via REST API")
        return ok(status.model_dump())
    except Exception as exc:
        log.critical("SW E-STOP failed: %s", exc)
        return err(str(exc), "MOTOR_ESTOP_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/enable  /  /api/motor/disable  (TMC260C-PA DRV_ENN)
# ---------------------------------------------------------------------------

class AxisEnableUpdate(BaseModel):
    """한 축의 코일 여자(enable) 설정."""
    model_config = {"extra": "forbid"}
    axis: int = Field(..., ge=0, le=3)
    enabled: bool = Field(..., description="True energizes the coils")
    exclusive: bool = Field(
        True,
        description="Silence every other axis first. The three drivers "
                    "share one STEP line, so anything else left energized "
                    "moves along with the commanded axis.")


@router.get("/axis-enable", response_model=ApiResponse)
async def get_axis_enable(svc: MotorService = Depends(_motor_service)) -> ApiResponse:
    """축별 코일 상태: 지금 여자되어 있는지, 유휴 시 유지하는지."""
    try:
        return ok(svc.axis_enable_state())
    except Exception as exc:
        return err(str(exc), "MOTOR_ENABLE_ERROR")


@router.put("/axis-enable", response_model=ApiResponse)
async def set_axis_enable(
    body: AxisEnableUpdate,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """한 축의 코일을 여자하거나 해제한다.

    M7 로 넘기는 /enable, /disable 과 달리 이 엔드포인트는 벤치의 드라이버
    칩을 직접 제어한다.
    """
    try:
        return ok(await svc.set_axis_enable(
            body.axis, body.enabled, exclusive=body.exclusive))
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), "MOTOR_ENABLE_ERROR")


@router.post("/enable", response_model=ApiResponse)
async def motor_enable(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """
    TMC260C-PA 의 DRV_ENN 을 어서트해 전 축의 스테퍼 코일을 다시 여자한다.
    호출 후 모터는 다시 위치를 유지한다.
    """
    try:
        status = await svc.enable_drivers()
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor enable failed: %s", exc)
        return err(str(exc), "MOTOR_ENABLE_ERROR")


@router.post("/disable", response_model=ApiResponse)
async def motor_disable(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """
    TMC260C-PA 코일을 해제한다(DRV_ENN 릴리스).

    아직 움직이는 축이 있으면 409 MOTOR_BUSY 로 거부한다 — 호출자는 먼저
    /stop 을 보내야 한다. VMot 12V 를 끊는 것이 아니라 일반적인 산업용
    드라이버 disable 이므로 클라이언트 코드에서 자유롭게 토글해도 안전하다.
    """
    try:
        current = await svc.get_status()
        if current.state not in (MotionState.IDLE, MotionState.FAULT, MotionState.ESTOP):
            return err(
                f"Cannot disable drivers in state {current.state.name} — stop motion first",
                "MOTOR_BUSY",
            )
        status = await svc.disable_drivers()
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor disable failed: %s", exc)
        return err(str(exc), "MOTOR_DISABLE_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/reset
# ---------------------------------------------------------------------------

@router.post("/reset", response_model=ApiResponse)
async def motor_reset(
    body: MotorResetRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """폴트 상태를 해제하고 모터 드라이버를 다시 활성화한다.

    벤치에서는 TMC26x 래치 해제 시퀀스까지 수행하므로, 래치된 단락 감지
    폴트를 풀려고 물리적으로 전원을 껐다 켤 필요가 없다. 응답의
    `fault_clear` 에는 그래도 폴트가 남은 축이 담긴다 — 그런 축은 실제로
    전원을 내려야 한다.
    """
    try:
        status = await svc.reset()
        data = status.model_dump()
        report = getattr(svc, "_last_fault_clear", None)
        if report:
            data["fault_clear"] = report
        return ok(data)
    except Exception as exc:
        log.error("Motor reset failed: %s", exc)
        return err(str(exc), "MOTOR_RESET_ERROR")
