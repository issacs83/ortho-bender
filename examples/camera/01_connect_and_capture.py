"""Connect to camera, capture a single JPEG frame, and disconnect."""
import os
import requests

BASE = os.environ.get("OB_API_BASE", "http://192.168.4.1:8000")

# Connect — returns device info and capabilities
r = requests.post(f"{BASE}/api/camera/connect")
data = r.json()["data"]
print(f"Connected: {data['device']['vendor']} {data['device']['model']}")
print(f"Supported features: {[k for k, v in data['capabilities'].items() if v['supported']]}")

# Capture single frame as JPEG
r = requests.post(f"{BASE}/api/camera/capture", params={"quality": 90})
with open("frame.jpg", "wb") as f:
    f.write(r.content)
print("Saved frame.jpg")

# Disconnect
requests.post(f"{BASE}/api/camera/disconnect")
