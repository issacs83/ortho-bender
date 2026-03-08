"""
Pydantic models for motor control API.
"""

from pydantic import BaseModel, Field


class JogRequest(BaseModel):
    direction: str = Field(description="'cw' or 'ccw'")
    steps: int = Field(ge=0, description="Number of steps")
    speed: int = Field(default=1000, ge=1, description="Max speed")
    accel: int = Field(default=100000, ge=1, description="Acceleration")
    decel: int = Field(default=100000, ge=1, description="Deceleration")


class MoveAbsRequest(BaseModel):
    direction: str = Field(description="'cw' or 'ccw'")
    steps: int = Field(ge=0, description="Absolute position in steps")
    speed: int = Field(default=1000, ge=1)
    accel: int = Field(default=100000, ge=1)
    decel: int = Field(default=100000, ge=1)


class InitRequest(BaseModel):
    direction: str = Field(default="cw", description="'cw' or 'ccw'")
    speed: int = Field(default=1000, ge=1)


class ConnectRequest(BaseModel):
    port: str = Field(default="/tmp/b2_motor_sim")
    baudrate: int = Field(default=19200)


class MotorStatus(BaseModel):
    name: str
    position_steps: int = 0
    position_physical: float = 0.0
    physical_unit: str = "deg"
    state: str = "unknown"  # idle, moving, error


class SystemStatus(BaseModel):
    connected: bool = False
    port: str = ""
    motors: dict[str, MotorStatus] = {}
    sensors: dict[str, bool] = {}
