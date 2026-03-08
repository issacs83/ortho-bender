"""
Motor control API. Ported from stub.cpp mc*/ml* functions.
"""

from ..protocol.constants import (
    CMD_MOVEVEL, CMD_MOVEABS, CMD_INIT, CMD_STOP, CMD_STOPDECL,
    CMD_GETSTATE, CMD_GETERROR, CMD_GETPOSITION, CMD_GETSENSORSTATE,
    CMD_SETTORQUE, CMD_SETRESOLUTION, CMD_SETSTALLGUARD, CMD_SETBRIGHTNESS,
    CMD_HELLO, CMD_GETVERSION,
    MID_BENDER, MID_FEEDER, MID_LIFTER, MID_CUTTER,
    DIR_CW, DIR_CCW, S_STOP, S_STALL,
    MOTOR_NAMES,
)
from .serial_client import client

# Motor resolution state (mirrors g_motorres in stub.cpp)
_motor_res = {MID_BENDER: 16, MID_FEEDER: 16, MID_LIFTER: 16, MID_CUTTER: 16}


def _pack_u32(val: int) -> bytes:
    """Pack unsigned 32-bit big-endian."""
    val = val & 0xFFFFFFFF
    return bytes([
        (val >> 24) & 0xFF,
        (val >> 16) & 0xFF,
        (val >> 8) & 0xFF,
        val & 0xFF,
    ])


def _pack_u24(val: int) -> bytes:
    """Pack unsigned 24-bit big-endian."""
    val = val & 0xFFFFFF
    return bytes([(val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF])


def _dir_byte(direction: str) -> int:
    return DIR_CCW if direction.lower() == "ccw" else DIR_CW


# -- Unit conversions (from stub.h macros) --

def get_res(motor_id: int) -> int:
    return _motor_res.get(motor_id, 16)


def deg_to_steps(deg: float, motor_id: int) -> int:
    """DEG2STEP from stub.h: (deg) / (1.8 / res)"""
    res = get_res(motor_id)
    return int(deg / (1.8 / res))


def steps_to_deg(steps: int, motor_id: int) -> float:
    """STEP2DEG from stub.h: (steps) * (1.8 / res)"""
    res = get_res(motor_id)
    return steps * (1.8 / res)


def mm_to_steps(mm: float) -> int:
    """MM2STEP from stub.h: DEG2STEP(MM2DEG(x), MID_FEEDER)"""
    deg = mm * 3.6  # MM2DEG
    return deg_to_steps(deg, MID_FEEDER)


def steps_to_mm(steps: int) -> float:
    """STEP2MM from stub.h: DEG2MM(STEP2DEG(x, MID_FEEDER))"""
    deg = steps_to_deg(steps, MID_FEEDER)
    return deg / 3.6


def position_physical(motor_id: int, steps: int) -> tuple[float, str]:
    """Convert steps to physical units for a motor."""
    if motor_id == MID_FEEDER:
        return steps_to_mm(steps), "mm"
    return steps_to_deg(steps, motor_id), "deg"


# -- Motor commands --

def move_vel(motor_id: int, direction: str, steps: int,
             speed: int = 1000, accel: int = 100000, decel: int = 100000) -> bool:
    """Velocity mode move. Ported from mcMoveVel."""
    data = bytes([motor_id, _dir_byte(direction)]) + \
        _pack_u32(steps) + _pack_u24(accel) + _pack_u24(speed) + _pack_u24(decel)
    ok, _ = client.send_command(CMD_MOVEVEL, data, expected_reply_data_len=15)
    return ok


def move_abs(motor_id: int, direction: str, steps: int,
             speed: int = 1000, accel: int = 100000, decel: int = 100000) -> bool:
    """Absolute position move. Ported from mcMoveAbs."""
    data = bytes([motor_id, _dir_byte(direction)]) + \
        _pack_u32(steps) + _pack_u24(accel) + _pack_u24(speed) + _pack_u24(decel)
    ok, _ = client.send_command(CMD_MOVEABS, data, expected_reply_data_len=15)
    return ok


def init_motor(motor_id: int, direction: str = "cw", speed: int = 1000) -> bool:
    """Home/init motor. Ported from mcInit."""
    data = bytes([motor_id, _dir_byte(direction)]) + _pack_u24(speed)
    ok, _ = client.send_command(CMD_INIT, data, expected_reply_data_len=5)
    return ok


def stop(motor_id: int) -> bool:
    """Immediate stop. Ported from mcStop."""
    ok, _ = client.send_command(CMD_STOP, bytes([motor_id]), expected_reply_data_len=1)
    return ok


def stop_all() -> bool:
    """Stop all motors."""
    results = [stop(mid) for mid in [MID_CUTTER, MID_BENDER, MID_LIFTER, MID_FEEDER]]
    return all(results)


def get_state(motor_id: int) -> int | None:
    """Get motor state (0=stopped, 1=moving). Ported from mcGetState."""
    ok, data = client.send_command(CMD_GETSTATE, bytes([motor_id]), expected_reply_data_len=2)
    if ok and len(data) >= 2:
        return data[1]
    return None


def get_error(motor_id: int) -> int | None:
    """Get motor error flags. Ported from mcGetError."""
    ok, data = client.send_command(CMD_GETERROR, bytes([motor_id]), expected_reply_data_len=2)
    if ok and len(data) >= 2:
        return data[1]
    return None


def get_position(motor_id: int) -> int | None:
    """Get motor position in steps. Ported from mcGetPos."""
    ok, data = client.send_command(CMD_GETPOSITION, bytes([motor_id]), expected_reply_data_len=6)
    if ok and len(data) >= 6:
        sign = data[1]
        pos = (data[2] << 24) | (data[3] << 16) | (data[4] << 8) | data[5]
        if sign == 1:
            pos = -pos
        return pos
    return None


def get_sensor_state() -> dict[str, bool] | None:
    """Get 5 sensor states. Ported from mcGetSensorState."""
    ok, data = client.send_command(CMD_GETSENSORSTATE, b"", expected_reply_data_len=5)
    if ok and len(data) >= 5:
        return {
            "bending": not bool(data[0]),    # inverted
            "feed0": bool(data[1]),
            "feed1": bool(data[2]),
            "retract": not bool(data[3]),    # inverted
            "cutter": not bool(data[4]),     # inverted
        }
    return None


def set_resolution(motor_id: int, res: int) -> bool:
    """Set microstepping resolution. Ported from mcSetRes."""
    _motor_res[motor_id] = 256 >> res
    data = bytes([motor_id, res])
    ok, _ = client.send_command(CMD_SETRESOLUTION, data, expected_reply_data_len=2)
    return ok


def set_torque(motor_id: int, torque: int) -> bool:
    """Set torque limit. Ported from mcSetTorqueLimit."""
    data = bytes([motor_id, torque & 0xFF])
    ok, _ = client.send_command(CMD_SETTORQUE, data, expected_reply_data_len=2)
    return ok


def set_stallguard(motor_id: int, threshold: int) -> bool:
    """Set StallGuard2 threshold. Ported from mcSetStallGuard."""
    data = bytes([motor_id, threshold & 0xFF])
    ok, _ = client.send_command(CMD_SETSTALLGUARD, data, expected_reply_data_len=2)
    return ok


def set_light(light_id: int, r: int, g: int, b: int, dim: float = 1.0) -> bool:
    """Set RGB light. Ported from mcSetLight."""
    data = bytes([light_id, int(r * dim), int(g * dim), int(b * dim)])
    ok, _ = client.send_command(CMD_SETBRIGHTNESS, data, expected_reply_data_len=4)
    return ok


def say_hello() -> bool:
    """HELLO handshake. Ported from mcSayHello."""
    ok, _ = client.send_command(CMD_HELLO, b"", expected_reply_data_len=0)
    return ok


def get_version() -> str | None:
    """Get firmware version string. Ported from mcGetVersion."""
    ok, data = client.send_command(CMD_GETVERSION, b"", expected_reply_data_len=5)
    if ok and len(data) >= 5:
        return data[:5].decode("ascii", errors="replace")
    return None


def in_motion(motor_id: int) -> bool:
    """Check if motor is moving. Ported from mlInMotion."""
    state = get_state(motor_id)
    return state is not None and state != 0


def get_all_status() -> dict:
    """Poll all motors and sensors for dashboard status."""
    motors = {}
    for mid, name in MOTOR_NAMES.items():
        pos = get_position(mid)
        state = get_state(mid)
        if pos is None:
            pos = 0
        phys, unit = position_physical(mid, pos)
        state_str = "unknown"
        if state is not None:
            state_str = "moving" if state != 0 else "idle"
        motors[name] = {
            "pos_steps": pos,
            "pos_physical": round(phys, 2),
            "unit": unit,
            "state": state_str,
        }

    sensors = get_sensor_state() or {
        "bending": False, "feed0": False, "feed1": False,
        "retract": False, "cutter": False,
    }

    return {"motors": motors, "sensors": sensors}


# -- High-level motor logic (from stub.cpp ml* functions) --

def ml_init(motor_id: int) -> bool:
    """High-level init with per-motor torque/SG config. Ported from mlInit."""
    configs = {
        MID_BENDER: (0x10, 10),
        MID_FEEDER: (0x12, 7),
        MID_LIFTER: (0x10, 8),
        MID_CUTTER: (0x1F, 8),
    }
    torque, sg = configs.get(motor_id, (0x10, 8))
    set_torque(motor_id, torque)
    set_stallguard(motor_id, sg)
    return init_motor(motor_id, "cw", 1000)
