#!/bin/bash
# board-snapshot.sh — Dump board state for handover verification
#
# Usage: ./board-snapshot.sh [--ip 192.168.77.2]
# Output: output/snapshots/board-snapshot-YYYYMMDD-HHMMSS.txt

set -euo pipefail

BOARD_IP="192.168.77.2"
[ "${1:-}" = "--ip" ] && BOARD_IP="$2"
[ $# -eq 1 ] && [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && BOARD_IP="$1"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SNAP_DIR="${PROJECT_ROOT}/output/snapshots"
mkdir -p "$SNAP_DIR"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTFILE="${SNAP_DIR}/board-snapshot-${TIMESTAMP}.txt"

echo "[snapshot] Connecting to ${BOARD_IP}..."

python3 "${PROJECT_ROOT}/tools/board-snapshot-worker.py" "$BOARD_IP" > "$OUTFILE"

echo "[snapshot] Saved to: ${OUTFILE}"
echo "[snapshot] $(wc -l < "$OUTFILE") lines captured."
