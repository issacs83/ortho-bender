"""Full inspection pipeline: connect → configure → capture → process → save."""
import json
import os
import time

import cv2
import numpy as np
import requests

BASE = os.environ.get("OB_API_BASE", "http://192.168.4.1:8000")

# 1. Connect and inspect capabilities
r = requests.post(f"{BASE}/api/camera/connect")
caps = r.json()["data"]["capabilities"]
device = r.json()["data"]["device"]
print(f"Camera: {device['vendor']} {device['model']}")

# 2. Configure for inspection
requests.post(f"{BASE}/api/camera/roi", json={"width": 1200, "height": 900})
requests.post(f"{BASE}/api/camera/roi/center")
requests.post(f"{BASE}/api/camera/exposure", json={"auto": False, "time_us": 5000})
requests.post(f"{BASE}/api/camera/gain", json={"auto": False, "value_db": 0})
if caps.get("pixel_format", {}).get("supported"):
    requests.post(f"{BASE}/api/camera/pixel-format", json={"format": "mono8"})
print("Camera configured for inspection")

# 3. Capture and process
r = requests.post(f"{BASE}/api/camera/capture", params={"quality": 95})
arr = np.frombuffer(r.content, dtype=np.uint8)
img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)

# Simple wire detection (example)
blurred = cv2.GaussianBlur(img, (5, 5), 0)
edges = cv2.Canny(blurred, 50, 150)
lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50,
                         minLineLength=100, maxLineGap=10)
print(f"Detected {len(lines) if lines is not None else 0} line segments")

# 4. Save results
cv2.imwrite("inspection_raw.jpg", img)
cv2.imwrite("inspection_edges.jpg", edges)

# Draw detected lines
result = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
if lines is not None:
    for line in lines:
        x1, y1, x2, y2 = line[0]
        cv2.line(result, (x1, y1), (x2, y2), (0, 255, 0), 2)
cv2.imwrite("inspection_result.jpg", result)
print("Results saved")

# 5. Check temperature
if caps.get("temperature", {}).get("supported"):
    r = requests.get(f"{BASE}/api/camera/temperature")
    print(f"Camera temperature: {r.json()['data']['value_c']}°C")

requests.post(f"{BASE}/api/camera/disconnect")
