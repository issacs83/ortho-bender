"""
Thread-safe serial client for B2 motor controller.
Ported from stub.cpp mcConnectComm/sendcmd/getack.

Supports both real serial ports (via pyserial) and PTY devices
(via raw file I/O, used by motor_sim).
"""

import os
import threading
import time
import select

from ..protocol.constants import BAUDRATE, CMD_HELLO
from ..protocol.frame import build_frame, parse_response


class SerialClient:
    """Thread-safe serial connection to B2 motor controller (or motor_sim)."""

    def __init__(self):
        self._fd: int | None = None
        self._lock = threading.Lock()
        self._port_path: str = ""

    @property
    def connected(self) -> bool:
        return self._fd is not None

    def connect(self, port: str, baudrate: int = BAUDRATE, timeout: int = 1) -> bool:
        """Connect and verify with HELLO handshake."""
        self.disconnect()
        try:
            import fcntl
            # Resolve symlinks (e.g., /tmp/b2_motor_sim -> /dev/pts/N)
            real_path = os.path.realpath(port)
            self._fd = os.open(real_path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            # Clear O_NONBLOCK after open (needed for PTY open, but blocking for I/O)
            flags = fcntl.fcntl(self._fd, fcntl.F_GETFL)
            fcntl.fcntl(self._fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
            self._port_path = port
            time.sleep(0.1)

            # Verify with HELLO
            ok, _ = self.send_command(CMD_HELLO, b"", expected_reply_data_len=0)
            if ok:
                return True
            self.disconnect()
            return False
        except OSError:
            self._fd = None
            return False

    def disconnect(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
            self._port_path = ""

    def send_command(
        self, cmd: int, data: bytes, expected_reply_data_len: int
    ) -> tuple[bool, bytes]:
        """
        Send a command frame and wait for ACK.
        Returns (success, reply_data).
        """
        with self._lock:
            if self._fd is None:
                return False, b""

            frame = build_frame(cmd, data)
            try:
                # Flush any pending input
                try:
                    while select.select([self._fd], [], [], 0)[0]:
                        os.read(self._fd, 4096)
                except Exception:
                    pass

                os.write(self._fd, frame)

                # Expected total reply size
                expected_total = expected_reply_data_len + 5

                # Poll for reply (up to 2s)
                raw = b""
                for _ in range(200):
                    ready, _, _ = select.select([self._fd], [], [], 0.01)
                    if ready:
                        chunk = os.read(self._fd, expected_total - len(raw))
                        raw += chunk
                        if len(raw) >= expected_total:
                            break

                if not raw:
                    return False, b""

                return parse_response(raw, cmd)

            except OSError:
                self.disconnect()
                return False, b""


# Global singleton
client = SerialClient()
