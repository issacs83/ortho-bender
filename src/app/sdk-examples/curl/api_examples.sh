#!/usr/bin/env bash
# api_examples.sh — curl examples for every Ortho-Bender SDK REST endpoint.
#
# Usage:
#   HOST=http://localhost:8000 bash api_examples.sh
#   HOST=http://192.168.1.100:8000 bash api_examples.sh   # real hardware

set -euo pipefail

HOST="${HOST:-http://localhost:8000}"
SEP="────────────────────────────────────"

echo "$SEP"
echo "Ortho-Bender SDK — API Examples"
echo "Host: $HOST"
echo "$SEP"

# Helper: pretty-print JSON
jq_or_cat() { command -v jq &>/dev/null && jq . || cat; }

# ===========================================================================
# System API
# ===========================================================================

echo -e "\n[GET] /api/system/status"
curl -s "$HOST/api/system/status" | jq_or_cat

echo -e "\n[GET] /api/system/version"
curl -s "$HOST/api/system/version" | jq_or_cat

# ===========================================================================
# Motor API
# ===========================================================================

echo -e "\n$SEP"
echo -e "\n[GET] /api/motor/status"
curl -s "$HOST/api/motor/status" | jq_or_cat

echo -e "\n[POST] /api/motor/home  (axis_mask=0 → all axes)"
curl -s -X POST "$HOST/api/motor/home" \
  -H "Content-Type: application/json" \
  -d '{"axis_mask": 0}' | jq_or_cat

echo -e "\n[POST] /api/motor/jog   (FEED axis, +direction, 5 mm)"
curl -s -X POST "$HOST/api/motor/jog" \
  -H "Content-Type: application/json" \
  -d '{"axis": 0, "direction": 1, "speed": 10.0, "distance": 5.0}' | jq_or_cat

echo -e "\n[POST] /api/motor/move  (BEND axis, 45 degrees)"
curl -s -X POST "$HOST/api/motor/move" \
  -H "Content-Type: application/json" \
  -d '{"axis": 1, "distance": 45.0, "speed": 30.0}' | jq_or_cat

echo -e "\n[POST] /api/motor/stop"
curl -s -X POST "$HOST/api/motor/stop" | jq_or_cat

echo -e "\n[POST] /api/motor/reset"
curl -s -X POST "$HOST/api/motor/reset" \
  -H "Content-Type: application/json" \
  -d '{"axis_mask": 0}' | jq_or_cat

# Uncomment to test E-STOP (halts motion immediately)
# echo -e "\n[POST] /api/motor/estop"
# curl -s -X POST "$HOST/api/motor/estop" | jq_or_cat

# ===========================================================================
# Camera API
# ===========================================================================

echo -e "\n$SEP"
echo -e "\n[GET] /api/camera/status"
curl -s "$HOST/api/camera/status" | jq_or_cat

echo -e "\n[POST] /api/camera/settings  (5 ms exposure, 6 dB gain)"
curl -s -X POST "$HOST/api/camera/settings" \
  -H "Content-Type: application/json" \
  -d '{"exposure_us": 5000, "gain_db": 6.0, "format": "mono8"}' | jq_or_cat

echo -e "\n[POST] /api/camera/capture   (saves frame.jpg)"
curl -s -o frame.jpg "$HOST/api/camera/capture?quality=90"
echo "  Saved to frame.jpg ($(wc -c < frame.jpg) bytes)"

echo -e "\n  MJPEG stream URL (open in browser or VLC):"
echo "  $HOST/api/camera/stream"

# ===========================================================================
# Bending API
# ===========================================================================

echo -e "\n$SEP"
echo -e "\n[POST] /api/bending/execute  (3-step SS 304 sequence)"
curl -s -X POST "$HOST/api/bending/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "steps": [
      {"L_mm": 10.0, "beta_deg":   0.0, "theta_deg": 30.0},
      {"L_mm": 15.0, "beta_deg":  90.0, "theta_deg": 45.0},
      {"L_mm": 20.0, "beta_deg": -90.0, "theta_deg": 60.0}
    ],
    "material": 0,
    "wire_diameter_mm": 0.457
  }' | jq_or_cat

echo -e "\n[GET] /api/bending/status"
curl -s "$HOST/api/bending/status" | jq_or_cat

echo -e "\n[POST] /api/bending/stop"
curl -s -X POST "$HOST/api/bending/stop" | jq_or_cat

# ===========================================================================
# WebSocket (informational)
# ===========================================================================

echo -e "\n$SEP"
echo "WebSocket endpoints (connect with wscat or browser DevTools):"
echo "  Motor stream : ws://${HOST#http://}/ws/motor"
echo "  Camera frames: ws://${HOST#http://}/ws/camera"
echo "  System events: ws://${HOST#http://}/ws/system"
echo ""
echo "Example (wscat):"
echo "  wscat -c ws://localhost:8000/ws/motor"

# ===========================================================================
# Health probe
# ===========================================================================

echo -e "\n$SEP"
echo -e "\n[GET] /health"
curl -s "$HOST/health" | jq_or_cat

echo -e "\n$SEP"
echo "Done."
