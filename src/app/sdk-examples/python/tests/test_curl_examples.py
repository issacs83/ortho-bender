"""test_curl_examples.py — curl/api_examples.sh 예제 검증.

bash 스크립트 자체를 subprocess 로 실행하여:
  - exit code 가 0
  - 주요 엔드포인트 섹션 헤더가 모두 출력됨
  - /api/camera/capture 가 frame.jpg 로 유효한 JPEG 저장
을 확인합니다. curl / bash 는 대부분의 리눅스에 기본 설치되어 있습니다.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "..", "curl", "api_examples.sh"))


pytestmark = pytest.mark.skipif(
    shutil.which("curl") is None or shutil.which("bash") is None,
    reason="curl/bash not available",
)


def test_curl_script_exists_and_executable():
    assert os.path.isfile(SCRIPT), f"missing script: {SCRIPT}"


def test_curl_script_runs_against_mock_backend(tmp_path, backend_url):
    env = os.environ.copy()
    env["HOST"] = backend_url

    proc = subprocess.run(
        ["bash", SCRIPT],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}"

    out = proc.stdout
    # 주요 엔드포인트 섹션이 모두 찍혔는지
    for marker in [
        "/api/system/status",
        "/api/motor/home",
        "/api/camera/capture",
        "/api/bending/execute",
        "/health",
        "Done.",
    ]:
        assert marker in out, f"missing section: {marker}"

    # camera capture 가 실제로 frame.jpg 를 저장했는지
    frame = tmp_path / "frame.jpg"
    assert frame.exists(), "frame.jpg not written"
    data = frame.read_bytes()
    assert len(data) > 100
    assert data[:3] == b"\xff\xd8\xff"
