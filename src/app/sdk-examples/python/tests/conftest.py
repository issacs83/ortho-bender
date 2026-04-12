"""conftest.py — 모든 테스트가 공유하는 fixture.

백엔드가 이미 떠 있으면 그것을 사용하고, 아니면 mock 모드로 자동 기동합니다.
실기기 CI 에서는 ORTHO_BENDER_URL 환경변수로 오버라이드 가능.
"""
import os
import sys
import time
import socket
import signal
import subprocess

import httpx
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_DIR = os.path.abspath(os.path.join(HERE, ".."))
# server.main:app 는 src/app 를 cwd 로 해야 import 가 풀립니다.
APP_DIR = os.path.abspath(os.path.join(HERE, "../../.."))

# cad_cam_opencv_workflow 를 import 할 수 있도록 경로 추가
sys.path.insert(0, EXAMPLE_DIR)


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


@pytest.fixture(scope="session")
def backend_url() -> str:
    host, port = "127.0.0.1", 8000
    url = f"http://{host}:{port}"

    override = os.environ.get("ORTHO_BENDER_URL")
    if override:
        yield override
        return

    if _port_open(host, port):
        yield url
        return

    env = os.environ.copy()
    env["OB_MOCK_MODE"] = "true"
    proc = subprocess.Popen(
        ["python3", "-m", "uvicorn", "server.main:app",
         "--host", host, "--port", str(port)],
        cwd=APP_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )

    started = False
    for _ in range(50):
        if _port_open(host, port):
            started = True
            break
        time.sleep(0.1)

    if not started:
        proc.terminate()
        pytest.fail("mock backend failed to start")

    yield url

    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


@pytest.fixture
def client(backend_url: str):
    with httpx.Client(base_url=backend_url, timeout=10.0) as c:
        yield c
