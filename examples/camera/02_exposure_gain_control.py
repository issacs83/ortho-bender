"""Control exposure and gain — manual and auto modes."""
import os
import requests

BASE = os.environ.get("OB_API_BASE", "http://192.168.4.1:8000")
requests.post(f"{BASE}/api/camera/connect")

# Check valid range
r = requests.get(f"{BASE}/api/camera/exposure")
info = r.json()["data"]
print(f"Exposure range: {info['range']['min']}–{info['range']['max']} μs")

# Set manual exposure
r = requests.post(f"{BASE}/api/camera/exposure", json={"auto": False, "time_us": 10000})
print(f"Exposure set to: {r.json()['data']['time_us']} μs")

# Switch to auto exposure
r = requests.post(f"{BASE}/api/camera/exposure", json={"auto": True})
print(f"Auto exposure — current value: {r.json()['data']['time_us']} μs")

# Set manual gain
r = requests.post(f"{BASE}/api/camera/gain", json={"auto": False, "value_db": 6.0})
print(f"Gain set to: {r.json()['data']['value_db']} dB")

requests.post(f"{BASE}/api/camera/disconnect")
