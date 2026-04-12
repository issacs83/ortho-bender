"""test_opencv_inspection.py — OpenCV 측정 함수 단위 테스트.

SDK 또는 백엔드 없이 순수 이미지 처리 로직만 검증.
"""
import numpy as np
import cv2
import pytest

from cad_cam_opencv_workflow import measure_max_bend_angle


def _synthetic_bend_image(angle_deg: float, size: int = 400) -> np.ndarray:
    """중심에서 지정된 각도로 꺾인 두 직선을 그린 흑백 이미지."""
    img = np.zeros((size, size), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    length = size // 3

    cv2.line(img, (cx - length, cy), (cx, cy), 255, 3)

    rad = np.radians(angle_deg)
    x2 = int(cx + length * np.cos(rad))
    y2 = int(cy - length * np.sin(rad))
    cv2.line(img, (cx, cy), (x2, y2), 255, 3)

    return img


def test_measures_zero_bend_from_straight_line():
    img = _synthetic_bend_image(0.0)
    angle, _ = measure_max_bend_angle(img)
    assert angle is None or angle < 5.0


@pytest.mark.parametrize("target", [30.0, 45.0, 60.0, 90.0])
def test_measures_approximate_angle(target):
    img = _synthetic_bend_image(target)
    angle, notes = measure_max_bend_angle(img)
    assert angle is not None, f"detection failed: {notes}"
    assert abs(angle - target) <= 5.0, f"target={target}, got {angle}"


def test_empty_frame_returns_none():
    angle, notes = measure_max_bend_angle(np.zeros((400, 400), dtype=np.uint8))
    assert angle is None
    assert notes
