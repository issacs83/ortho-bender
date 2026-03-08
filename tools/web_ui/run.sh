#!/bin/bash
# Launch ortho-bender web dashboard with motor simulator.
#
# Usage:
#   ./run.sh              # start motor_sim + web server
#   ./run.sh --no-sim     # web server only (connect to real hardware)
#   ./run.sh --port 8080  # custom web port

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SIM_BUILD="$PROJECT_ROOT/build-kc-test"
SIM_BIN="$SIM_BUILD/motor_sim"
WEB_PORT="${ORTHO_WEB_PORT:-8080}"
USE_SIM=1
SIM_PID=""

for arg in "$@"; do
    case "$arg" in
        --no-sim) USE_SIM=0 ;;
        --port)   shift; WEB_PORT="$1" ;;
        --help|-h)
            echo "Usage: $0 [--no-sim] [--port PORT]"
            exit 0
            ;;
    esac
done

cleanup() {
    echo ""
    echo ">>> Shutting down..."
    [ -n "$SIM_PID" ] && kill "$SIM_PID" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# Build motor_sim if needed
if [ "$USE_SIM" -eq 1 ]; then
    if [ ! -f "$SIM_BIN" ]; then
        echo ">>> Building motor_sim..."
        cmake -B "$SIM_BUILD" -S "$PROJECT_ROOT/tools/kc_port" -DUSE_CAMERA=OFF -DUSE_MOTOR=ON
        cmake --build "$SIM_BUILD" --target motor_sim
    fi

    echo ">>> Starting motor_sim..."
    "$SIM_BIN" --speed-factor 10 &
    SIM_PID=$!
    sleep 1

    if ! kill -0 "$SIM_PID" 2>/dev/null; then
        echo "ERROR: motor_sim failed to start"
        exit 1
    fi
    echo ">>> motor_sim running (PID=$SIM_PID)"
fi

# Install Python deps
pip install -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null

echo ""
echo ">>> Starting web dashboard on http://0.0.0.0:$WEB_PORT"
echo ">>> Press Ctrl+C to stop"
echo ""

cd "$SCRIPT_DIR"
ORTHO_WEB_PORT="$WEB_PORT" python -m uvicorn ortho_bender_web.main:app \
    --host 0.0.0.0 --port "$WEB_PORT" --log-level info

cleanup
