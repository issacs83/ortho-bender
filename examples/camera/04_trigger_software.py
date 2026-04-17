"""Software trigger mode — capture on demand."""
import os
import requests
import time

BASE = os.environ.get("OB_API_BASE", "http://192.168.4.1:8000")
requests.post(f"{BASE}/api/camera/connect")

# Set software trigger mode
requests.post(f"{BASE}/api/camera/trigger", json={"mode": "software"})
print("Software trigger mode active")

# Fire trigger and capture
for i in range(5):
    requests.post(f"{BASE}/api/camera/trigger/fire")
    r = requests.post(f"{BASE}/api/camera/capture")
    with open(f"triggered_{i}.jpg", "wb") as f:
        f.write(r.content)
    print(f"Captured triggered_{i}.jpg")
    time.sleep(0.5)

# Return to freerun
requests.post(f"{BASE}/api/camera/trigger", json={"mode": "freerun"})
requests.post(f"{BASE}/api/camera/disconnect")
