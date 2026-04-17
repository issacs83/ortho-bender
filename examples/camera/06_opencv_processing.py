"""Capture frame and process with OpenCV."""
import os

import cv2
import numpy as np
import requests

BASE = os.environ.get("OB_API_BASE", "http://192.168.4.1:8000")
requests.post(f"{BASE}/api/camera/connect")

# Capture JPEG, decode to numpy
r = requests.post(f"{BASE}/api/camera/capture")
arr = np.frombuffer(r.content, dtype=np.uint8)
img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
print(f"Frame shape: {img.shape}")

# Edge detection
edges = cv2.Canny(img, 100, 200)
cv2.imwrite("edges.jpg", edges)
print("Saved edges.jpg")

# Threshold
_, binary = cv2.threshold(img, 128, 255, cv2.THRESH_BINARY)
cv2.imwrite("binary.jpg", binary)
print("Saved binary.jpg")

# Histogram
hist = cv2.calcHist([img], [0], None, [256], [0, 256])
print(f"Mean intensity: {img.mean():.1f}, Std: {img.std():.1f}")

requests.post(f"{BASE}/api/camera/disconnect")
