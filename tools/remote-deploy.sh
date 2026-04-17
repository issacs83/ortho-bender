#!/bin/bash
# remote-deploy.sh — Remote deployment to Ortho-Bender EVK board
#
# Deploys individual components over SSH (paramiko/sshpass).
# Board must be reachable at BOARD_IP via Ethernet or WiFi AP.
#
# Usage:
#   ./remote-deploy.sh [component] [options]
#
# Components:
#   all         Deploy everything
#   dtb         Device tree blob only
#   kernel      Linux kernel Image + DTB
#   m7          M7 FreeRTOS firmware (hot-reload, no reboot)
#   backend     FastAPI backend (restart service, no reboot)
#   frontend    React frontend dist
#   config      Network + systemd configs
#   extlinux    Boot menu (extlinux.conf)
#   ipk FILE    Install .ipk package(s)
#
# Options:
#   --reboot    Reboot board after deploy
#   --ip ADDR   Override board IP (default: 192.168.77.2)
#   --dry-run   Show what would be done without executing
#
# Examples:
#   ./remote-deploy.sh m7                    # Hot-reload M7 firmware
#   ./remote-deploy.sh backend               # Sync & restart FastAPI
#   ./remote-deploy.sh dtb --reboot          # Deploy DTB + reboot
#   ./remote-deploy.sh all --reboot          # Full deployment
#   ./remote-deploy.sh ipk /path/to/*.ipk    # Install packages

set -euo pipefail

# === Configuration ===
BOARD_IP="${BOARD_IP:-192.168.77.2}"
BOARD_USER="root"
BOARD_PASS="ortho-bender"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Build output paths
BUILD_DIR="${PROJECT_ROOT}/build-ortho-bender"
DEPLOY_DIR="${BUILD_DIR}/tmp/deploy/images/ortho-bender-imx8mp"
IPK_DIR="${BUILD_DIR}/tmp/deploy/ipk"
FW_BUILD_DIR="${PROJECT_ROOT}/build-firmware"

# Board paths
BOOT_PART="/run/media/boot-mmcblk2p1"
OPT_DIR="/opt/ortho-bender"
FW_DIR="/lib/firmware"

# State
DRY_RUN=false
DO_REBOOT=false
COMPONENT=""
IPK_FILES=()

# === Helpers ===
log()  { echo "[deploy] $*"; }
warn() { echo "[deploy] WARNING: $*" >&2; }
die()  { echo "[deploy] ERROR: $*" >&2; exit 1; }

# SSH/SCP wrapper using paramiko (dropbear rejects openssh password auth)
remote_exec() {
    python3 -c "
import paramiko, sys
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('${BOARD_IP}', username='${BOARD_USER}', password='${BOARD_PASS}', timeout=10)
stdin, stdout, stderr = c.exec_command(sys.argv[1])
out = stdout.read().decode()
err = stderr.read().decode()
rc = stdout.channel.recv_exit_status()
if out: print(out, end='')
if err: print(err, end='', file=sys.stderr)
c.close()
sys.exit(rc)
" "$1"
}

remote_upload() {
    local src="$1" dst="$2"
    python3 -c "
import paramiko, sys
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('${BOARD_IP}', username='${BOARD_USER}', password='${BOARD_PASS}', timeout=10)
sftp = c.open_sftp()
sftp.put(sys.argv[1], sys.argv[2])
sftp.close()
c.close()
print(f'  uploaded: {sys.argv[1]} -> {sys.argv[2]}')
" "$src" "$dst"
}

remote_upload_dir() {
    local src="$1" dst="$2"
    python3 -c "
import paramiko, os, sys
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('${BOARD_IP}', username='${BOARD_USER}', password='${BOARD_PASS}', timeout=10)
sftp = c.open_sftp()

src_dir = sys.argv[1]
dst_dir = sys.argv[2]
count = 0

for root, dirs, files in os.walk(src_dir):
    rel = os.path.relpath(root, src_dir)
    remote_root = os.path.join(dst_dir, rel) if rel != '.' else dst_dir
    try:
        sftp.mkdir(remote_root)
    except IOError:
        pass
    for f in files:
        if f.startswith('.') or f.endswith('.pyc') or '__pycache__' in root:
            continue
        local_path = os.path.join(root, f)
        remote_path = os.path.join(remote_root, f)
        sftp.put(local_path, remote_path)
        count += 1

sftp.close()
c.close()
print(f'  uploaded {count} files: {src_dir} -> {dst_dir}')
" "$src" "$dst"
}

check_connectivity() {
    log "Checking board connectivity at ${BOARD_IP}..."
    remote_exec "echo OK" >/dev/null 2>&1 || die "Cannot reach board at ${BOARD_IP}"
    log "Board reachable."
}

# === Deploy Functions ===

deploy_dtb() {
    log "=== Deploying DTB ==="
    local dtb="${DEPLOY_DIR}/imx8mp-ortho-bender.dtb"
    local dtb_prebuilt="${PROJECT_ROOT}/output/dtb/imx8mp-ortho-bender.dtb"

    if [ -f "$dtb" ]; then
        local src="$dtb"
    elif [ -f "$dtb_prebuilt" ]; then
        local src="$dtb_prebuilt"
        warn "Using pre-built DTB (not from latest Yocto build)"
    else
        die "DTB not found. Build first or place in output/dtb/"
    fi

    if $DRY_RUN; then log "  [dry-run] upload $src -> ${BOOT_PART}/imx8mp-ortho-bender.dtb"; return; fi

    remote_upload "$src" "${BOOT_PART}/imx8mp-ortho-bender.dtb"
    log "DTB deployed. Reboot required to take effect."
}

deploy_kernel() {
    log "=== Deploying Kernel Image ==="
    local img="${DEPLOY_DIR}/Image"
    [ -f "$img" ] || die "Kernel Image not found at ${img}"

    if $DRY_RUN; then log "  [dry-run] upload Image + DTB"; return; fi

    remote_upload "$img" "${BOOT_PART}/Image"
    deploy_dtb
    log "Kernel + DTB deployed. Reboot required."
}

deploy_m7() {
    log "=== Deploying M7 Firmware (hot-reload) ==="
    local fw="${FW_BUILD_DIR}/ortho-bender-firmware.bin"
    [ -f "$fw" ] || die "M7 firmware not found at ${fw}. Run: cmake --build build-firmware"

    if $DRY_RUN; then log "  [dry-run] upload + remoteproc reload"; return; fi

    remote_upload "$fw" "${FW_DIR}/ortho-bender-firmware.bin"

    log "  Stopping M7 remoteproc..."
    remote_exec "echo stop > /sys/class/remoteproc/remoteproc0/state 2>/dev/null || true"

    log "  Setting firmware name..."
    remote_exec "echo ortho-bender-firmware.bin > /sys/class/remoteproc/remoteproc0/firmware"

    log "  Starting M7..."
    remote_exec "echo start > /sys/class/remoteproc/remoteproc0/state"

    log "  Verifying..."
    local state
    state=$(remote_exec "cat /sys/class/remoteproc/remoteproc0/state")
    if [ "$state" = "running" ]; then
        log "M7 firmware deployed and running. No reboot needed."
    else
        warn "M7 state: ${state} (expected: running)"
    fi
}

deploy_backend() {
    log "=== Deploying FastAPI Backend ==="
    local src="${PROJECT_ROOT}/src/app/server"
    [ -d "$src" ] || die "Backend source not found at ${src}"

    if $DRY_RUN; then log "  [dry-run] sync server/ + restart service"; return; fi

    remote_upload_dir "$src" "${OPT_DIR}/server"

    log "  Restarting ortho-bender-sdk.service..."
    remote_exec "systemctl restart ortho-bender-sdk.service"
    sleep 2

    local status
    status=$(remote_exec "systemctl is-active ortho-bender-sdk.service 2>/dev/null || echo failed")
    if [ "$status" = "active" ]; then
        log "Backend deployed and running. No reboot needed."
    else
        warn "Service status: ${status}"
        remote_exec "journalctl -u ortho-bender-sdk.service --no-pager -n 10" || true
    fi
}

deploy_frontend() {
    log "=== Deploying Frontend ==="
    local src="${PROJECT_ROOT}/src/app/frontend/dist"
    [ -d "$src" ] || die "Frontend dist not found at ${src}. Run: cd src/app/frontend && npm run build"

    if $DRY_RUN; then log "  [dry-run] sync frontend-dist/"; return; fi

    remote_upload_dir "$src" "${OPT_DIR}/frontend-dist"
    log "Frontend deployed. No reboot needed."
}

deploy_config() {
    log "=== Deploying Config Files ==="

    if $DRY_RUN; then log "  [dry-run] upload network configs"; return; fi

    # eth0 static IP
    local eth0_net="${PROJECT_ROOT}/meta-ortho-bender/recipes-core/systemd/systemd-conf/10-eth0.network"
    if [ -f "$eth0_net" ]; then
        remote_upload "$eth0_net" "/etc/systemd/network/10-eth0.network"
        log "  10-eth0.network deployed."
    fi

    remote_exec "systemctl restart systemd-networkd"
    log "Config deployed."
}

deploy_extlinux() {
    log "=== Deploying extlinux.conf ==="

    if $DRY_RUN; then log "  [dry-run] update extlinux default"; return; fi

    # Set ortho-bender as default boot entry
    remote_exec "sed -i 's/^DEFAULT .*/DEFAULT emmc-ortho-bender/' ${BOOT_PART}/extlinux/extlinux.conf"
    log "extlinux default set to emmc-ortho-bender. Reboot to apply."
}

deploy_ipk() {
    log "=== Installing IPK Packages ==="
    [ ${#IPK_FILES[@]} -gt 0 ] || die "No .ipk files specified"

    if $DRY_RUN; then log "  [dry-run] install ${#IPK_FILES[@]} packages"; return; fi

    for ipk in "${IPK_FILES[@]}"; do
        [ -f "$ipk" ] || { warn "File not found: ${ipk}"; continue; }
        local basename
        basename=$(basename "$ipk")
        remote_upload "$ipk" "/tmp/${basename}"
        remote_exec "opkg install /tmp/${basename} 2>&1 || true"
        log "  Installed: ${basename}"
    done
}

deploy_all() {
    log "=== Full Deployment ==="
    deploy_config
    deploy_dtb
    deploy_backend
    [ -d "${PROJECT_ROOT}/src/app/frontend/dist" ] && deploy_frontend || warn "Frontend dist not found, skipping."
    [ -f "${FW_BUILD_DIR}/ortho-bender-firmware.bin" ] && deploy_m7 || warn "M7 firmware not built, skipping."
    log "Full deployment complete."
}

do_reboot() {
    log "=== Rebooting Board ==="
    if $DRY_RUN; then log "  [dry-run] reboot"; return; fi
    remote_exec "reboot" || true
    log "Reboot initiated. Board will be back in ~10 seconds."
}

# === Parse Arguments ===
while [ $# -gt 0 ]; do
    case "$1" in
        all|dtb|kernel|m7|backend|frontend|config|extlinux)
            COMPONENT="$1"; shift ;;
        ipk)
            COMPONENT="ipk"; shift
            while [ $# -gt 0 ] && [[ ! "$1" =~ ^-- ]]; do
                IPK_FILES+=("$1"); shift
            done ;;
        --reboot)  DO_REBOOT=true; shift ;;
        --ip)      BOARD_IP="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help)
            head -28 "$0" | tail -27; exit 0 ;;
        *)
            die "Unknown argument: $1. Use --help for usage." ;;
    esac
done

[ -n "$COMPONENT" ] || die "No component specified. Use: $0 [all|dtb|kernel|m7|backend|frontend|config|extlinux|ipk]"

# === Execute ===
check_connectivity

case "$COMPONENT" in
    all)       deploy_all ;;
    dtb)       deploy_dtb ;;
    kernel)    deploy_kernel ;;
    m7)        deploy_m7 ;;
    backend)   deploy_backend ;;
    frontend)  deploy_frontend ;;
    config)    deploy_config ;;
    extlinux)  deploy_extlinux ;;
    ipk)       deploy_ipk ;;
esac

$DO_REBOOT && do_reboot

log "Done."
