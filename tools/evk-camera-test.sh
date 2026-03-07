#!/bin/bash
# evk-camera-test.sh — CSI MIPI camera test on i.MX8MP-EVK
#
# Usage (on EVK):
#   ./evk-camera-test.sh              # auto-detect and capture
#   ./evk-camera-test.sh --list       # list devices only
#   ./evk-camera-test.sh --stream 5   # stream for 5 seconds
#
# Supported cameras: OV5640, AP1302, OS08A20 (NXP EVK defaults)
# Output: /tmp/camera_test_YYYYMMDD_HHMMSS.jpg

set -e

CAPTURE_DIR="/tmp"
STREAM_DURATION=0
LIST_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --list)     LIST_ONLY=1 ;;
        --stream)   shift; STREAM_DURATION="${1:-5}" ;;
        --help|-h)
            echo "Usage: $0 [--list] [--stream SECONDS]"
            echo "  --list          List V4L2 devices and media entities"
            echo "  --stream N      Capture N seconds of frames (default: single shot)"
            exit 0
            ;;
    esac
done

echo "=== i.MX8MP CSI MIPI Camera Test ==="
echo ""

# ── Step 1: List devices ──
echo "[1/4] Listing V4L2 devices..."
if command -v v4l2-ctl &>/dev/null; then
    v4l2-ctl --list-devices 2>/dev/null || echo "  (no devices found)"
else
    echo "  WARNING: v4l2-ctl not found. Install v4l-utils."
    echo "  Falling back to /dev/video* scan."
fi

echo ""
echo "Video device nodes:"
ls -la /dev/video* 2>/dev/null || echo "  No /dev/video* devices found"

echo ""
echo "Media devices:"
ls -la /dev/media* 2>/dev/null || echo "  No /dev/media* devices found"

if [ "$LIST_ONLY" -eq 1 ]; then
    echo ""
    echo "[Media topology]"
    for m in /dev/media*; do
        echo "--- $m ---"
        media-ctl -d "$m" -p 2>/dev/null || echo "  (cannot query)"
    done
    exit 0
fi

# ── Step 2: Find ISI capture device for CSI1 ──
echo ""
echo "[2/4] Detecting CSI1 MIPI camera pipeline..."

# On i.MX8MP, the ISI (Image Sensing Interface) creates video nodes.
# Typical topology:
#   sensor (e.g., ov5640) → csi2 bridge → mux → ISI channel → /dev/videoN
#
# We look for the ISI capture node associated with CSI1.

VIDEO_DEV=""

# Method 1: Try media-ctl to find the ISI pipeline
for m in /dev/media*; do
    ENTITIES=$(media-ctl -d "$m" -p 2>/dev/null || true)
    if echo "$ENTITIES" | grep -qi "isi"; then
        # Find video device node from ISI channel
        ISI_VIDEO=$(echo "$ENTITIES" | grep -A5 "isi-cap" | grep "/dev/video" | head -1 | grep -o '/dev/video[0-9]*')
        if [ -n "$ISI_VIDEO" ]; then
            VIDEO_DEV="$ISI_VIDEO"
            echo "  Found ISI capture: $VIDEO_DEV (via $m)"
            break
        fi
    fi
done

# Method 2: Fallback — try each /dev/video* with v4l2-ctl
if [ -z "$VIDEO_DEV" ]; then
    for v in /dev/video*; do
        CAPS=$(v4l2-ctl -d "$v" --all 2>/dev/null | head -20 || true)
        if echo "$CAPS" | grep -qi "capture"; then
            VIDEO_DEV="$v"
            echo "  Found capture device: $VIDEO_DEV (fallback scan)"
            break
        fi
    done
fi

if [ -z "$VIDEO_DEV" ]; then
    echo "  ERROR: No capture device found."
    echo "  Check:"
    echo "    1. Camera module connected to CSI1 (J10 on EVK)"
    echo "    2. Device tree enables csi1 + mipi_csi1"
    echo "    3. Camera driver loaded: lsmod | grep ov5640"
    exit 1
fi

# ── Step 3: Configure pipeline with media-ctl ──
echo ""
echo "[3/4] Configuring media pipeline..."

# Try to set format on sensor → ISI pipeline
# This is camera-specific. OV5640 example:
SENSOR_ENTITY=$(media-ctl -d /dev/media0 -p 2>/dev/null | grep -i "ov5640\|os08a20\|ap1302" | head -1 | sed 's/.*entity.*"\(.*\)".*/\1/' || true)

if [ -n "$SENSOR_ENTITY" ]; then
    echo "  Sensor: $SENSOR_ENTITY"
    # Set 640x480 UYVY on sensor output
    media-ctl -d /dev/media0 -V "'${SENSOR_ENTITY}':0[fmt:UYVY8_2X8/640x480]" 2>/dev/null || true
else
    echo "  WARNING: Could not identify sensor entity. Using default pipeline."
fi

# Set capture format
v4l2-ctl -d "$VIDEO_DEV" --set-fmt-video=width=640,height=480,pixelformat=YUYV 2>/dev/null || \
v4l2-ctl -d "$VIDEO_DEV" --set-fmt-video=width=640,height=480,pixelformat=UYVY 2>/dev/null || \
    echo "  WARNING: Could not set capture format. Using device default."

echo "  Capture format:"
v4l2-ctl -d "$VIDEO_DEV" --get-fmt-video 2>/dev/null || true

# ── Step 4: Capture ──
echo ""
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT="${CAPTURE_DIR}/camera_test_${TIMESTAMP}"

if [ "$STREAM_DURATION" -gt 0 ]; then
    echo "[4/4] Streaming for ${STREAM_DURATION} seconds..."
    OUTPUT_RAW="${OUTPUT}.raw"
    v4l2-ctl -d "$VIDEO_DEV" --stream-mmap --stream-count=$((STREAM_DURATION * 30)) \
        --stream-to="$OUTPUT_RAW" 2>&1 || true
    echo "  Raw frames saved: $OUTPUT_RAW"
    ls -lh "$OUTPUT_RAW" 2>/dev/null
else
    echo "[4/4] Capturing single frame..."

    # Method 1: Use v4l2-ctl to grab one frame
    OUTPUT_RAW="${OUTPUT}.raw"
    v4l2-ctl -d "$VIDEO_DEV" --stream-mmap --stream-count=1 \
        --stream-to="$OUTPUT_RAW" 2>&1

    if [ -f "$OUTPUT_RAW" ] && [ -s "$OUTPUT_RAW" ]; then
        # Convert raw to JPEG if ffmpeg is available
        if command -v ffmpeg &>/dev/null; then
            OUTPUT_JPG="${OUTPUT}.jpg"
            FMT=$(v4l2-ctl -d "$VIDEO_DEV" --get-fmt-video 2>/dev/null | grep "Pixel Format" | awk '{print $4}' || echo "YUYV")
            case "$FMT" in
                YUYV|"'YUYV'") FFMPEG_FMT="yuyv422" ;;
                UYVY|"'UYVY'") FFMPEG_FMT="uyvy422" ;;
                *)             FFMPEG_FMT="yuyv422" ;;
            esac
            ffmpeg -y -f rawvideo -pix_fmt "$FFMPEG_FMT" \
                -s 640x480 -i "$OUTPUT_RAW" \
                -frames:v 1 "$OUTPUT_JPG" 2>/dev/null
            if [ -f "$OUTPUT_JPG" ]; then
                echo "  JPEG saved: $OUTPUT_JPG"
                ls -lh "$OUTPUT_JPG"
                rm -f "$OUTPUT_RAW"
            else
                echo "  Raw saved (ffmpeg conversion failed): $OUTPUT_RAW"
            fi
        else
            echo "  Raw saved (install ffmpeg for JPEG): $OUTPUT_RAW"
            ls -lh "$OUTPUT_RAW"
        fi
    else
        echo "  ERROR: Capture failed. No data received."
        echo "  Try: v4l2-ctl -d $VIDEO_DEV --stream-mmap --stream-count=1"
        exit 1
    fi
fi

echo ""
echo "=== Test Complete ==="
