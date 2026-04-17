"""Save and restore camera settings via UserSet."""
import os
import requests

BASE = os.environ.get("OB_API_BASE", "http://192.168.4.1:8000")
requests.post(f"{BASE}/api/camera/connect")

# Configure camera
requests.post(f"{BASE}/api/camera/exposure", json={"auto": False, "time_us": 8000})
requests.post(f"{BASE}/api/camera/gain", json={"auto": False, "value_db": 3.0})
requests.post(f"{BASE}/api/camera/roi", json={"width": 1024, "height": 768})
print("Settings configured")

# Save to UserSet1
requests.post(f"{BASE}/api/camera/user-set/save", json={"slot": "UserSet1"})
print("Saved to UserSet1")

# Change settings
requests.post(f"{BASE}/api/camera/exposure", json={"auto": False, "time_us": 1000})
print("Changed exposure to 1000 μs")

# Restore from UserSet1
requests.post(f"{BASE}/api/camera/user-set/load", json={"slot": "UserSet1"})
r = requests.get(f"{BASE}/api/camera/exposure")
print(f"Restored exposure: {r.json()['data']['time_us']} μs")  # → 8000

# Set as default (auto-load on power up)
requests.post(f"{BASE}/api/camera/user-set/default", json={"slot": "UserSet1"})
print("UserSet1 set as power-on default")

requests.post(f"{BASE}/api/camera/disconnect")
