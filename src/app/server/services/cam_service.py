"""
cam_service.py — 3D wire centerline → B-code converter.

Pure-Python implementation of the discretization + bend extraction pipeline.
Mirrors the C++ CamEngine in src/app/cam/ but lives entirely in the Python
server so the SDK can run without a native build toolchain.

Algorithm (bend-per-vertex model):
  1. Build per-segment direction vectors from the polyline.
  2. For each interior vertex, compute the bend angle (theta) as the
     angle between adjacent segment directions.
  3. Rotation (beta) is the torsion angle between the incoming binormal
     and the outgoing binormal projected onto the plane perpendicular to
     the incoming direction.
  4. Feed (L) is the length of the segment preceding the vertex.
  5. Springback compensation applies a per-material overbend factor.

This is a simplified geometric model suitable for SDK-level validation
and frontend previewing. Final production bending uses the C++ CamEngine
with full finite-element springback compensation on the A53 host.

IEC 62304 SW Class: B (non-safety-critical preview only)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from ..models.schemas import BcodeStep, Point3D, WireMaterial


# Per-material empirical springback overbend factor.
# Mirrors routers/bending.py _SPRINGBACK_FACTOR.
_SPRINGBACK_FACTOR: dict[int, float] = {
    WireMaterial.SS_304:  1.10,
    WireMaterial.NITI:    1.35,
    WireMaterial.BETA_TI: 1.15,
    WireMaterial.CU_NITI: 1.30,
}


@dataclass
class CamResult:
    steps: list[BcodeStep]
    segment_count: int
    total_length_mm: float
    max_bend_deg: float
    warnings: list[str]


Vec3 = tuple[float, float, float]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec3) -> Vec3:
    n = _norm(a)
    if n < 1e-9:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _resample(points: Sequence[Point3D], min_segment_mm: float) -> list[Vec3]:
    """
    Re-parameterize the polyline so every segment is at least
    `min_segment_mm` long. Very short segments are merged into the
    next by dropping intermediate vertices. Segments longer than
    2 × min_segment_mm are left as-is (no subdivision).
    """
    if len(points) < 2:
        raise ValueError("CAM requires at least 2 points")

    pts: list[Vec3] = [(p.x, p.y, p.z) for p in points]
    out: list[Vec3] = [pts[0]]
    for v in pts[1:]:
        if _norm(_sub(v, out[-1])) >= min_segment_mm:
            out.append(v)
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def generate_bcode(
    points: Sequence[Point3D],
    material: WireMaterial,
    wire_diameter_mm: float,
    min_segment_mm: float = 1.0,
    apply_springback: bool = True,
) -> CamResult:
    """
    Convert a 3D polyline into a B-code sequence.

    Returns exactly N-2 bend steps for N input vertices (two endpoints
    contribute feed only). The first returned step carries the feed from
    point 0 → point 1; the final feed (to reach point N-1) is emitted as
    a zero-theta tail step.
    """
    warnings: list[str] = []
    resampled = _resample(points, min_segment_mm)
    if len(resampled) < 2:
        raise ValueError("CAM resampling produced fewer than 2 vertices")

    factor = _SPRINGBACK_FACTOR.get(int(material), 1.0) if apply_springback else 1.0

    # Per-segment direction unit vectors (length N-1)
    segs = [_sub(resampled[i + 1], resampled[i]) for i in range(len(resampled) - 1)]
    lens = [_norm(s) for s in segs]
    dirs = [_unit(s) for s in segs]

    steps: list[BcodeStep] = []
    prev_binormal: Vec3 | None = None
    max_bend = 0.0
    total_length = sum(lens)

    for i in range(len(dirs) - 1):
        L = lens[i]
        d_in = dirs[i]
        d_out = dirs[i + 1]

        cos_t = max(-1.0, min(1.0, _dot(d_in, d_out)))
        theta_raw = math.degrees(math.acos(cos_t))

        binormal = _unit(_cross(d_in, d_out))
        if _norm(binormal) < 1e-6:
            # Straight segment — no bend, carry previous binormal
            binormal = prev_binormal or (0.0, 0.0, 1.0)
            beta = 0.0
        elif prev_binormal is None:
            beta = 0.0
        else:
            # Torsion = signed angle between prev and current binormals
            # projected onto plane perpendicular to d_in.
            ref = prev_binormal
            ref_proj = _unit(_sub(ref, _scale(d_in, _dot(ref, d_in))))
            cur_proj = _unit(_sub(binormal, _scale(d_in, _dot(binormal, d_in))))
            cos_b = max(-1.0, min(1.0, _dot(ref_proj, cur_proj)))
            sign = 1.0 if _dot(_cross(ref_proj, cur_proj), d_in) >= 0 else -1.0
            beta = sign * math.degrees(math.acos(cos_b))

        theta = min(theta_raw * factor, 180.0)
        max_bend = max(max_bend, theta)

        if L < 0.5:
            warnings.append(f"step {i}: feed {L:.3f} mm below minimum; clamped to 0.5")
            L = 0.5

        steps.append(BcodeStep(
            L_mm=round(L, 4),
            beta_deg=round(beta, 3),
            theta_deg=round(theta, 3),
        ))
        prev_binormal = binormal

    # Tail feed step (final segment, zero bend)
    if len(dirs) >= 1 and lens[-1] >= 0.5:
        steps.append(BcodeStep(
            L_mm=round(lens[-1], 4),
            beta_deg=0.0,
            theta_deg=0.0,
        ))

    if len(steps) > 128:
        warnings.append(f"step count {len(steps)} exceeds 128 — truncated")
        steps = steps[:128]

    return CamResult(
        steps=steps,
        segment_count=len(segs),
        total_length_mm=round(total_length, 3),
        max_bend_deg=round(max_bend, 3),
        warnings=warnings,
    )
