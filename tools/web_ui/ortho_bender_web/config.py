"""
Configuration for ortho-bender web dashboard.
"""
import os

SERIAL_PORT = os.environ.get("ORTHO_SERIAL_PORT", "/tmp/b2_motor_sim")
SERIAL_BAUD = int(os.environ.get("ORTHO_SERIAL_BAUD", "19200"))
WEB_HOST = os.environ.get("ORTHO_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("ORTHO_WEB_PORT", "8080"))
STATUS_POLL_HZ = 10
