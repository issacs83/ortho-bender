#!/bin/bash
# Cross-build kc_test for i.MX8MP (aarch64)
#
# Usage:
#   ./build-imx8mp.sh              # motor-only (no OpenCV needed)
#   ./build-imx8mp.sh --camera     # full build (requires OpenCV aarch64)
#   ./build-imx8mp.sh --clean      # clean build directory
#
# Deploy to EVK:
#   scp build-imx8mp/kc_test_motor_only root@<EVK_IP>:/home/root/

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build-imx8mp"
TOOLCHAIN="${SCRIPT_DIR}/cmake/aarch64-linux-gnu.cmake"

USE_CAMERA=OFF
CLEAN=0

for arg in "$@"; do
    case "$arg" in
        --camera)  USE_CAMERA=ON ;;
        --clean)   CLEAN=1 ;;
        --help|-h)
            echo "Usage: $0 [--camera] [--clean]"
            echo "  --camera   Enable OpenCV camera support (requires aarch64 OpenCV)"
            echo "  --clean    Remove build directory and rebuild"
            exit 0
            ;;
    esac
done

if [ "$CLEAN" -eq 1 ]; then
    echo ">>> Cleaning ${BUILD_DIR}"
    rm -rf "${BUILD_DIR}"
fi

echo ">>> Configuring (USE_CAMERA=${USE_CAMERA})"
cmake -B "${BUILD_DIR}" -S "${SCRIPT_DIR}" \
    --toolchain "${TOOLCHAIN}" \
    -DUSE_CAMERA="${USE_CAMERA}" \
    -DUSE_MOTOR=ON \
    -DCMAKE_BUILD_TYPE=Release

echo ">>> Building"
cmake --build "${BUILD_DIR}" -- -j"$(nproc)"

echo ""
echo ">>> Build complete:"
ls -lh "${BUILD_DIR}"/kc_test*
echo ""
file "${BUILD_DIR}"/kc_test*
echo ""
echo ">>> Deploy: scp ${BUILD_DIR}/kc_test_motor_only root@<EVK_IP>:/home/root/"
