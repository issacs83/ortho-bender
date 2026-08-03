"""Set ROI and pixel format."""
import os
import requests

BASE = os.environ.get("OB_API_BASE", "http://192.168.4.1:8000")
requests.post(f"{BASE}/api/camera/connect")

# Set ROI to center 800x600
r = requests.post(f"{BASE}/api/camera/roi", json={"width": 800, "height": 600})
data = r.json()["data"]
print(f"ROI: {data['width']}x{data['height']} at ({data['offset_x']},{data['offset_y']})")

# Check if frame_rate was invalidated
if "frame_rate" in data.get("invalidated", []):
    r = requests.get(f"{BASE}/api/camera/frame-rate")
    print(f"New max FPS: {r.json()['data']['range']['max']}")

# Center the ROI
r = requests.post(f"{BASE}/api/camera/roi/center")
data = r.json()["data"]
print(f"Centered at ({data['offset_x']},{data['offset_y']})")

# Change pixel format
r = requests.post(f"{BASE}/api/camera/pixel-format", json={"format": "mono12"})
print(f"Format: {r.json()['data']['format']}")

requests.post(f"{BASE}/api/camera/disconnect")
