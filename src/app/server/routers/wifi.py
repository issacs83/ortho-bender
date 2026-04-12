"""
routers/wifi.py — /api/wifi/* REST endpoints.

WiFi management via wpa_cli. Supports scan, connect, disconnect, and status.
Requires wpa_supplicant running on the target interface (mlan0).

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..config import get_settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wifi", tags=["wifi"])

IFACE = "mlan0"


def _is_mock() -> bool:
    """Return True when running in mock mode (no hardware available)."""
    try:
        return get_settings().mock_mode
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Mock responses (no wpa_cli required)
# ---------------------------------------------------------------------------

def _mock_status_response() -> dict:
    return {
        "success": True,
        "data": {
            "connected": False,
            "ssid": None,
            "ip_address": None,
            "bssid": None,
            "wpa_state": "DISCONNECTED",
            "freq": None,
        },
    }


def _mock_scan_response() -> dict:
    return {
        "success": True,
        "data": [
            {
                "bssid": "aa:bb:cc:dd:ee:ff",
                "frequency": 2412,
                "signal": -65,
                "flags": "[WPA2-PSK-CCMP][ESS]",
                "security": "WPA2",
                "band": "2.4G",
                "ssid": "MockNetwork",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_wpa_cli(*args: str) -> tuple[str, int]:
    """Run wpa_cli command and return (stdout, returncode)."""
    proc = await asyncio.create_subprocess_exec(
        "wpa_cli", "-i", IFACE, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = stdout.decode().strip()
    if proc.returncode != 0 and stderr:
        log.warning("wpa_cli %s: stderr=%s", args, stderr.decode().strip())
    return output, proc.returncode or 0


async def _ensure_wpa_supplicant() -> bool:
    """Check if wpa_supplicant is running; attempt to start it if not."""
    proc = await asyncio.create_subprocess_exec(
        "pgrep", "-f", "wpa_supplicant",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode == 0:
        return True

    # Attempt to start wpa_supplicant
    log.info("wpa_supplicant not running — attempting to start")
    start = await asyncio.create_subprocess_exec(
        "wpa_supplicant", "-B", "-i", IFACE,
        "-c", "/etc/wpa_supplicant.conf",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await start.communicate()
    if start.returncode != 0:
        log.error("Failed to start wpa_supplicant: %s", stderr.decode().strip())
        return False
    await asyncio.sleep(1)
    return True


def _parse_flags(flags: str) -> str:
    """Extract security type string from wpa_scan_results flags field."""
    if not flags or flags == "[ESS]":
        return "OPEN"
    if "WPA2" in flags:
        return "WPA2"
    if "WPA" in flags:
        return "WPA"
    return "OPEN"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class WifiConnectRequest(BaseModel):
    ssid: str
    password: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def wifi_status():
    """Get current WiFi connection status from wpa_supplicant."""
    if _is_mock():
        return _mock_status_response()

    if not await _ensure_wpa_supplicant():
        return {"success": False, "error": "wpa_supplicant not available"}

    result, _ = await _run_wpa_cli("status")
    lines = result.split("\n")
    info: dict[str, str] = {}
    for line in lines:
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()

    connected = info.get("wpa_state") == "COMPLETED"
    return {
        "success": True,
        "data": {
            "connected": connected,
            "ssid": info.get("ssid"),
            "ip_address": info.get("ip_address"),
            "bssid": info.get("bssid"),
            "wpa_state": info.get("wpa_state"),
            "freq": int(info["freq"]) if "freq" in info else None,
        },
    }


@router.get("/scan")
async def wifi_scan():
    """Trigger a WiFi scan and return available networks sorted by signal strength."""
    if _is_mock():
        return _mock_scan_response()

    if not await _ensure_wpa_supplicant():
        return {"success": False, "error": "wpa_supplicant not available"}

    await _run_wpa_cli("scan")
    await asyncio.sleep(3)

    result, _ = await _run_wpa_cli("scan_results")
    lines = result.strip().split("\n")

    networks: list[dict] = []
    for line in lines[1:]:  # skip header line
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        bssid, freq_str, signal_str, flags, ssid = (
            parts[0], parts[1], parts[2], parts[3], parts[4],
        )

        # Filter out hidden networks (empty or null-byte SSIDs)
        if not ssid or ssid.startswith("\\x00"):
            ssid = "(hidden)"

        try:
            freq = int(freq_str)
            signal = int(signal_str)
        except ValueError:
            continue

        networks.append({
            "bssid": bssid,
            "frequency": freq,
            "signal": signal,
            "flags": flags,
            "security": _parse_flags(flags),
            "band": "5G" if freq >= 5000 else "2.4G",
            "ssid": ssid,
        })

    # Strongest signal first
    networks.sort(key=lambda n: n["signal"], reverse=True)
    return {"success": True, "data": networks}


@router.post("/connect")
async def wifi_connect(req: WifiConnectRequest):
    """Connect to a WiFi network using wpa_cli."""
    if _is_mock():
        return {
            "success": True,
            "data": {"connected": False, "net_id": "0", "note": "mock mode"},
        }

    if not await _ensure_wpa_supplicant():
        return {"success": False, "error": "wpa_supplicant not available"}

    # Add a new network entry
    net_id, rc = await _run_wpa_cli("add_network")
    if rc != 0 or not net_id.isdigit():
        return {"success": False, "error": f"add_network failed: {net_id}"}

    await _run_wpa_cli("set_network", net_id, "ssid", f'"{req.ssid}"')

    if req.password:
        await _run_wpa_cli("set_network", net_id, "psk", f'"{req.password}"')
    else:
        await _run_wpa_cli("set_network", net_id, "key_mgmt", "NONE")

    await _run_wpa_cli("enable_network", net_id)
    await _run_wpa_cli("select_network", net_id)
    await _run_wpa_cli("save_config")

    # Wait for wpa_supplicant to associate
    await asyncio.sleep(5)

    status_out, _ = await _run_wpa_cli("status")
    connected = "wpa_state=COMPLETED" in status_out

    # Request DHCP lease if newly connected
    if connected:
        try:
            dhcp = await asyncio.create_subprocess_exec(
                "udhcpc", "-i", IFACE, "-n", "-q",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(dhcp.communicate(), timeout=10)
        except (asyncio.TimeoutError, FileNotFoundError):
            log.warning("udhcpc unavailable or timed out on %s", IFACE)

    return {
        "success": True,
        "data": {"connected": connected, "net_id": net_id},
    }


@router.post("/disconnect")
async def wifi_disconnect():
    """Disconnect from the current WiFi network."""
    if _is_mock():
        return {"success": True, "data": {"connected": False}}

    await _run_wpa_cli("disconnect")
    return {"success": True, "data": {"connected": False}}
