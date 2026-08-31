#!/usr/bin/env bash
##
# dev.sh — 빌드 / 테스트 / 배포 / 디버깅 단일 진입점
#
#   tools/dev.sh setup                 호스트 툴체인 점검 + .clangd + .vscode + 컴파일DB 생성
#   tools/dev.sh build <타깃> [옵션]   app|app-arm|tests|tests-arm|kc|firmware|all
#   tools/dev.sh test  <스위트>        py(=두 스위트 전부)|py-server|py-root|cpp|cpp-board|safety
#   tools/dev.sh deploy <대상>         server|docs|frontend|bin|all
#   tools/dev.sh debug py [--wait|--stop|--status|--install]
#   tools/dev.sh debug cpp <바이너리> [-- 인자...]
#   tools/dev.sh debug stop | debug m7
#   tools/dev.sh ip [--write] | status | sync | clean
#
# 여기서 만드는 빌드는 기본이 -O0 -g3 이다. 그래야 브레이크포인트가
# 정확히 그 소스 줄에서 멈춘다. 최적화 빌드는 --release (디버깅용 아님).
##
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BOARD_USER="${OB_BOARD_USER:-root}"
BOARD_PASS="${OB_BOARD_PASS:-ortho-bender}"
BOARD_OPT="/opt/ortho-bender"
BOARD_BIN="$BOARD_OPT/bin"
DEBUGPY_PORT="${OB_DEBUGPY_PORT:-5678}"
GDBSERVER_PORT="${OB_GDBSERVER_PORT:-2345}"
DEBUG_UNIT="ortho-bender-sdk-debug"
PROD_UNIT="ortho-bender-sdk"

# 디버그 빌드 플래그: 최적화 없음, 최대 디버그 정보, 프레임 포인터 유지.
# -fno-inline 까지 넣어야 인라인된 함수 안에도 브레이크포인트가 걸린다.
DEBUG_C_FLAGS="-O0 -g3 -fno-omit-frame-pointer -fno-inline"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
log()  { echo "${c_grn}[dev]${c_off} $*"; }
warn() { echo "${c_ylw}[dev] 경고:${c_off} $*" >&2; }
die()  { echo "${c_red}[dev] 오류:${c_off} $*" >&2; exit 1; }
step() { echo; echo "${c_dim}── $* ──${c_off}"; }

# ─────────────────────────────────────────────────────────────
# 보드 접속
# ─────────────────────────────────────────────────────────────

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o HostKeyAlgorithms=+ssh-rsa -o ConnectTimeout=10 -o LogLevel=ERROR)

# 포트가 열려 있는지만 본다. nc 가 없어도 되도록 bash 의 /dev/tcp 를 쓴다.
port_open() { timeout 3 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null; }

# 보드 IP는 움직인다(WiFi/USB이더넷은 DHCP). 기억이 아니라 열린 포트로 확인한다.
#
# 캐시된 IP의 판정 기준은 :22(SSH)다. :8000 을 기준으로 삼으면 백엔드가
# 잠깐 내려가 있을 때 배포·gdbserver 같은 SSH 작업까지 전부 막히고,
# 애먼 서브넷 스캔이 1분씩 돈다.
board_ip() {
    if [[ -n "${OB_BOARD_IP:-}" ]]; then echo "$OB_BOARD_IP"; return; fi
    if [[ -s "$ROOT/.board-ip" ]]; then
        local ip; ip="$(tr -d '[:space:]' < "$ROOT/.board-ip")"
        if port_open "$ip" 22; then echo "$ip"; return; fi
        warn "캐시된 .board-ip ($ip) 의 SSH 포트가 닫혀 있음 — 재탐색"
    fi
    local found
    # find-board.py 는 스캔 로그도 같이 찍는다. "IP -> {json}" 형태로
    # SDK 라고 확인된 줄만 골라야 게이트웨이 IP 를 잡지 않는다.
    found="$(python3 "$ROOT/tools/find-board.py" 2>/dev/null \
             | grep -oE '^[[:space:]]+([0-9]{1,3}\.){3}[0-9]{1,3} -> \{' \
             | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1)" || true
    [[ -n "$found" ]] || die "보드를 찾지 못함. OB_BOARD_IP=<ip> 를 지정하거나 tools/find-board.py 실행"
    echo "$found" > "$ROOT/.board-ip"
    echo "$found"
}

# 보드(Yocto 이미지)에는 ss 가 없고 netstat 만 있다. 둘 다 감당하는 스니펫.
REMOTE_PORTS='(command -v ss >/dev/null && ss -lntp || netstat -lntp) 2>/dev/null'

bssh() { local ip; ip="$(board_ip)"; sshpass -p "$BOARD_PASS" ssh "${SSH_OPTS[@]}" "$BOARD_USER@$ip" "$@"; }
bscp() { sshpass -p "$BOARD_PASS" scp "${SSH_OPTS[@]}" "$@"; }
btgt() { echo "$BOARD_USER@$(board_ip)"; }

# ─────────────────────────────────────────────────────────────
# setup — 툴체인 점검, 빌드트리 구성, 에디터 설정 생성
# ─────────────────────────────────────────────────────────────

HOST_PKGS=(cmake ninja-build gcc g++ gdb gdb-multiarch clangd
           gcc-aarch64-linux-gnu g++-aarch64-linux-gnu
           libgtest-dev googletest gcc-arm-none-eabi openocd sshpass rsync)

cmd_setup() {
    step "호스트 툴체인"
    local missing=()
    for t in cmake ninja gcc g++ gdb gdb-multiarch clangd \
             aarch64-linux-gnu-gcc aarch64-linux-gnu-g++ arm-none-eabi-gcc \
             openocd sshpass rsync; do
        if command -v "$t" >/dev/null; then
            printf '  %-24s %s\n' "$t" "$(command -v "$t")"
        else
            printf '  %-24s %s없음%s\n' "$t" "$c_red" "$c_off"; missing+=("$t")
        fi
    done
    if ((${#missing[@]})); then
        warn "누락: ${missing[*]}"
        echo "  sudo apt-get install -y ${HOST_PKGS[*]}"
        [[ "${1:-}" == "--install" ]] && sudo apt-get install -y "${HOST_PKGS[@]}"
    fi

    step "빌드 트리 구성"
    configure app     || warn "app 구성 실패"
    configure tests   || warn "tests 구성 실패"
    configure app-arm || warn "app-arm 구성 실패"

    gen_compdb
    gen_clangd
    gen_vscode
    log "설정 완료 — VS Code 창을 새로고침하면 .clangd / launch.json 이 반영된다"
}

# ─────────────────────────────────────────────────────────────
# build
# ─────────────────────────────────────────────────────────────

BUILD_TYPE=Debug
DO_CLEAN=0

build_dir_for() {
    case "$1" in
        app)       echo "$ROOT/build-app" ;;
        app-arm)   echo "$ROOT/build-app-arm" ;;
        tests)     echo "$ROOT/build-tests" ;;
        tests-arm) echo "$ROOT/build-tests-arm" ;;
        kc)        echo "$ROOT/build-kc-arm" ;;
        firmware)  echo "$ROOT/build-firmware" ;;
        *) die "알 수 없는 빌드 타깃 '$1' (app|app-arm|tests|tests-arm|kc|firmware|all)" ;;
    esac
}

configure() {
    local target="$1" bdir; bdir="$(build_dir_for "$target")"
    (( DO_CLEAN )) && { log "클린: $bdir"; rm -rf "$bdir"; }

    local common=(-G Ninja -DCMAKE_BUILD_TYPE="$BUILD_TYPE" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON)
    if [[ "$BUILD_TYPE" == Debug ]]; then
        common+=(-DCMAKE_C_FLAGS_DEBUG="$DEBUG_C_FLAGS" -DCMAKE_CXX_FLAGS_DEBUG="$DEBUG_C_FLAGS")
    fi

    case "$target" in
        app)       cmake -S "$ROOT/src/app"  -B "$bdir" "${common[@]}" ;;
        tests)     cmake -S "$ROOT/tests"    -B "$bdir" "${common[@]}" ;;
        app-arm)   cmake -S "$ROOT/src/app"  -B "$bdir" "${common[@]}" \
                         --toolchain "$ROOT/cmake/aarch64-linux-gnu.cmake" ;;
        tests-arm) cmake -S "$ROOT/tests"    -B "$bdir" "${common[@]}" \
                         --toolchain "$ROOT/cmake/aarch64-linux-gnu.cmake" ;;
        kc)        cmake -S "$ROOT/tools/kc_port" -B "$bdir" "${common[@]}" \
                         --toolchain "$ROOT/cmake/aarch64-linux-gnu.cmake" \
                         -DUSE_CAMERA=OFF -DUSE_MOTOR=ON ;;
        firmware)
            # M7 펌웨어는 MCUXpresso SDK(FreeRTOS + rpmsg_lite + MIMX8ML8)가 있어야 빌드된다.
            local sdk="${OB_M7_SDK:-$HOME/.openclaw/workspace/m7_sdk}"
            [[ -d "$sdk" ]] || die "MCUXpresso SDK 를 $sdk 에서 찾지 못함.
  i.MX8MP SDK(FreeRTOS + rpmsg_lite + MIMX8ML8 디바이스 파일)를 설치한 뒤:
      OB_M7_SDK=/경로/sdk tools/dev.sh build firmware"
            command -v arm-none-eabi-gcc >/dev/null || die "arm-none-eabi-gcc 없음 (sudo apt install gcc-arm-none-eabi)"
            cmake -S "$ROOT/src/firmware" -B "$bdir" "${common[@]}" \
                  --toolchain "$ROOT/cmake/arm-none-eabi.cmake" -DSDK_DIR="$sdk" ;;
    esac
}

cmd_build() {
    local targets=() a
    for a in "$@"; do
        case "$a" in
            --clean)   DO_CLEAN=1 ;;
            --release) BUILD_TYPE=Release ;;
            --debug)   BUILD_TYPE=Debug ;;
            all)       targets+=(app tests app-arm tests-arm kc) ;;
            -*)        die "알 수 없는 옵션 $a" ;;
            *)         targets+=("$a") ;;
        esac
    done
    ((${#targets[@]})) || targets=(app tests)

    local t bdir
    for t in "${targets[@]}"; do
        bdir="$(build_dir_for "$t")"
        step "빌드 $t  [$BUILD_TYPE]  -> ${bdir#$ROOT/}"
        configure "$t"
        cmake --build "$bdir" -j "$(nproc)"
    done
    gen_compdb
}

# ─────────────────────────────────────────────────────────────
# 컴파일 DB + clangd — 코드/함수 추적(정의로 이동, 참조 찾기)의 근거
# ─────────────────────────────────────────────────────────────

gen_compdb() {
    python3 - "$ROOT" <<'PY'
import json, sys, pathlib
root = pathlib.Path(sys.argv[1])
# 네이티브 빌드를 먼저 넣는다. clangd 는 한 파일에 대해 처음 만난 항목을 쓰는데,
# 호스트 네이티브 플래그가 clangd 가 실제로 해석할 수 있는 플래그이기 때문.
order = ["build-app", "build-tests", "build-app-arm", "build-tests-arm",
         "build-kc-arm", "build-firmware"]
merged, seen = [], set()
for d in order:
    p = root / d / "compile_commands.json"
    if not p.is_file():
        continue
    for e in json.loads(p.read_text()):
        key = e["file"]
        if key in seen:
            continue
        seen.add(key)
        merged.append(e)
out = root / "compile_commands.json"
# 예전에 build-app/compile_commands.json 을 가리키는 심볼릭 링크가 있었다.
# 그대로 쓰면 병합 결과가 빌드 디렉터리 안으로 들어가 버리고, 다음 cmake 실행에
# 덮여 사라진다. 링크면 지우고 실제 파일로 만든다.
if out.is_symlink():
    out.unlink()
out.write_text(json.dumps(merged, indent=1) + "\n")
trees = len([d for d in order if (root / d / "compile_commands.json").is_file()])
print(f"[dev] compile_commands.json: 빌드트리 {trees}개에서 항목 {len(merged)}개")
PY
}

gen_clangd() {
    cat > "$ROOT/.clangd" <<EOF
# tools/dev.sh setup 이 생성함 — 직접 수정하지 말 것.
CompileFlags:
  CompilationDatabase: .

---
# 펌웨어/공용 C 소스.
#  - clangd 는 x86 clang 이라 Cortex-M 플래그(-mcpu 등)를 해석하지 못하니 제거한다.
#  - 컴파일 DB 에 없는 .c 파일은 clangd 가 가까운 항목(여기서는 C++ 타깃)의 플래그를
#    빌려 쓰는 바람에 -x c++ 로 열리고 "-std=c11 not allowed with C++" 로 죽는다.
#    그래서 -xc 로 언어를 못 박는다. 확장자로 매치해야 tests 의 .cpp 가 안 걸린다.
If:
  PathMatch: (src/firmware|src/shared)/.*\\.(c|h)
CompileFlags:
  Add:
    - -xc
    - -std=c11
    - -Wno-unknown-attributes
    - -I$ROOT/src/firmware
    - -I$ROOT/src/firmware/board
    - -I$ROOT/src/firmware/hal
    - -I$ROOT/src/firmware/linker
    - -I$ROOT/src/firmware/source
    - -I$ROOT/src/firmware/source/drivers
    - -I$ROOT/src/firmware/source/ipc
    - -I$ROOT/src/firmware/source/motion
    - -I$ROOT/src/firmware/source/safety
    - -I$ROOT/src/shared
  Remove:
    - -mcpu=*
    - -mfpu=*
    - -mfloat-abi=*
    - -mthumb

---
# A53 앱(C++): 컴파일 DB 에 없는 헤더도 바로 따라갈 수 있게 경로를 보강.
If:
  PathMatch: src/app/(cam|ipc)/.*
CompileFlags:
  Add:
    - -std=gnu++17
    - -I$ROOT/src/app/cam
    - -I$ROOT/src/app/ipc
    - -I$ROOT/src/shared
EOF
    log ".clangd 재생성 (CompilationDatabase: 저장소 루트)"
}

# ─────────────────────────────────────────────────────────────
# .vscode — launch / tasks / settings 생성
# ─────────────────────────────────────────────────────────────

gen_vscode() {
    local ip; ip="$(board_ip 2>/dev/null || echo 192.168.77.2)"
    mkdir -p "$ROOT/.vscode"

    cat > "$ROOT/.vscode/launch.json" <<EOF
{
  // tools/dev.sh setup 이 생성함. 보드 IP 가 생성 시점 값으로 박혀 있다.
  // IP 는 움직이므로 바뀌면 \`tools/dev.sh setup\` 을 다시 실행할 것.
  "version": "0.2.0",
  "configurations": [
    {
      // 보드에서 실제로 도는 FastAPI 프로세스에 붙는다.
      // pathMappings 덕분에 호스트 소스 줄에 찍은 중단점이 보드에서 멈춘다.
      "name": "PY · 보드 attach (debugpy $ip:$DEBUGPY_PORT)",
      "type": "debugpy",
      "request": "attach",
      "connect": { "host": "$ip", "port": $DEBUGPY_PORT },
      "pathMappings": [
        { "localRoot": "\${workspaceFolder}/src/app/server", "remoteRoot": "$BOARD_OPT/server" }
      ],
      "justMyCode": false,
      "redirectOutput": true,
      "presentation": { "group": "1-board", "order": 1 }
    },
    {
      // 하드웨어 없이 동일 API 를 띄운다(모터 호출은 전부 무동작).
      "name": "PY · 로컬 uvicorn (mock 모드)",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["server.main:app", "--host", "127.0.0.1", "--port", "8000"],
      "cwd": "\${workspaceFolder}/src/app",
      "env": { "OB_MOCK_MODE": "true", "PYTHONPATH": "\${workspaceFolder}/src/app" },
      "justMyCode": false,
      "console": "integratedTerminal",
      "presentation": { "group": "2-host", "order": 1 }
    },
    {
      "name": "PY · pytest (열린 파일)",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["-q", "\${file}"],
      "cwd": "\${workspaceFolder}/src/app/server",
      "env": { "OB_MOCK_MODE": "true" },
      "justMyCode": false,
      "console": "integratedTerminal",
      "presentation": { "group": "2-host", "order": 2 }
    },
    {
      "name": "C++ · 호스트 gtest: cam_engine",
      "type": "cppdbg",
      "request": "launch",
      "program": "\${workspaceFolder}/build-tests/test_cam_engine",
      "args": [],
      "cwd": "\${workspaceFolder}",
      "MIMode": "gdb",
      "miDebuggerPath": "/usr/bin/gdb",
      "preLaunchTask": "빌드: tests (Debug)",
      "setupCommands": [
        { "description": "STL 값 보기 좋게 출력", "text": "-enable-pretty-printing", "ignoreFailures": true }
      ],
      "presentation": { "group": "2-host", "order": 3 }
    },
    {
      "name": "C++ · 호스트 gtest: wire_materials",
      "type": "cppdbg",
      "request": "launch",
      "program": "\${workspaceFolder}/build-tests/test_wire_materials",
      "args": [],
      "cwd": "\${workspaceFolder}",
      "MIMode": "gdb",
      "miDebuggerPath": "/usr/bin/gdb",
      "preLaunchTask": "빌드: tests (Debug)",
      "setupCommands": [
        { "description": "STL 값 보기 좋게 출력", "text": "-enable-pretty-printing", "ignoreFailures": true }
      ],
      "presentation": { "group": "2-host", "order": 4 }
    },
    {
      // 보드에서 gdbserver 가 실행하고, 심볼은 호스트의 크로스빌드 산출물에서 읽는다.
      // sysroot remote:/ 는 보드 쪽 공유 라이브러리를 gdb 연결로 가져오는 설정.
      "name": "C++ · 보드 gdbserver attach — kc_test_motor_only",
      "type": "cppdbg",
      "request": "launch",
      "program": "\${workspaceFolder}/build-kc-arm/kc_test_motor_only",
      "cwd": "\${workspaceFolder}",
      "MIMode": "gdb",
      "miDebuggerPath": "/usr/bin/gdb-multiarch",
      "miDebuggerServerAddress": "$ip:$GDBSERVER_PORT",
      "targetArchitecture": "arm64",
      "stopAtConnect": true,
      "preLaunchTask": "보드: gdbserver kc_test_motor_only",
      "postDebugTask": "보드: gdbserver 정지",
      "setupCommands": [
        { "text": "set architecture aarch64", "ignoreFailures": true },
        { "text": "set sysroot remote:/", "ignoreFailures": true },
        { "description": "STL 값 보기 좋게 출력", "text": "-enable-pretty-printing", "ignoreFailures": true }
      ],
      "presentation": { "group": "1-board", "order": 2 }
    },
    {
      "name": "C++ · 보드 gdbserver attach — gtest cam_engine",
      "type": "cppdbg",
      "request": "launch",
      "program": "\${workspaceFolder}/build-tests-arm/test_cam_engine",
      "cwd": "\${workspaceFolder}",
      "MIMode": "gdb",
      "miDebuggerPath": "/usr/bin/gdb-multiarch",
      "miDebuggerServerAddress": "$ip:$GDBSERVER_PORT",
      "targetArchitecture": "arm64",
      "stopAtConnect": true,
      "preLaunchTask": "보드: gdbserver test_cam_engine",
      "postDebugTask": "보드: gdbserver 정지",
      "setupCommands": [
        { "text": "set architecture aarch64", "ignoreFailures": true },
        { "text": "set sysroot remote:/", "ignoreFailures": true },
        { "description": "STL 값 보기 좋게 출력", "text": "-enable-pretty-printing", "ignoreFailures": true }
      ],
      "presentation": { "group": "1-board", "order": 3 }
    },
    {
      // M7 펌웨어는 JTAG 프로브가 물려 있어야 한다. interface/*.cfg 를 실제 프로브로 교체할 것.
      "name": "M7 · JTAG (openocd + gdb-multiarch)",
      "type": "cppdbg",
      "request": "launch",
      "program": "\${workspaceFolder}/build-firmware/ortho-bender-firmware.elf",
      "cwd": "\${workspaceFolder}",
      "MIMode": "gdb",
      "miDebuggerPath": "/usr/bin/gdb-multiarch",
      "miDebuggerServerAddress": "localhost:3333",
      "debugServerPath": "/usr/bin/openocd",
      "debugServerArgs": "-f interface/jlink.cfg -f target/imx8m.cfg",
      "filterStderr": true,
      "serverStarted": "Listening on port 3333",
      "targetArchitecture": "arm",
      "stopAtConnect": true,
      "setupCommands": [
        { "text": "set architecture armv7e-m", "ignoreFailures": true },
        { "text": "monitor reset halt", "ignoreFailures": true },
        { "text": "load", "ignoreFailures": false }
      ],
      "presentation": { "group": "3-firmware", "order": 1 }
    }
  ]
}
EOF

    cat > "$ROOT/.vscode/tasks.json" <<EOF
{
  // tools/dev.sh setup 이 생성함. 모든 작업은 tools/dev.sh 로 위임한다.
  "version": "2.0.0",
  "tasks": [
    {
      "label": "빌드: app (Debug)",
      "type": "shell", "command": "tools/dev.sh build app",
      "group": "build", "problemMatcher": ["\$gcc"]
    },
    {
      "label": "빌드: tests (Debug)",
      "type": "shell", "command": "tools/dev.sh build tests",
      "group": { "kind": "build", "isDefault": true }, "problemMatcher": ["\$gcc"]
    },
    {
      "label": "빌드: aarch64 (app-arm + tests-arm + kc)",
      "type": "shell", "command": "tools/dev.sh build app-arm tests-arm kc",
      "group": "build", "problemMatcher": ["\$gcc"]
    },
    {
      "label": "빌드: 펌웨어 (M7)",
      "type": "shell", "command": "tools/dev.sh build firmware",
      "group": "build", "problemMatcher": ["\$gcc"]
    },
    {
      "label": "빌드: 전체 클린 빌드",
      "type": "shell", "command": "tools/dev.sh build all --clean",
      "group": "build", "problemMatcher": ["\$gcc"]
    },
    {
      "label": "테스트: python (mock)",
      "type": "shell", "command": "tools/dev.sh test py",
      "group": { "kind": "test", "isDefault": true }, "problemMatcher": []
    },
    {
      "label": "테스트: C++ (호스트)",
      "type": "shell", "command": "tools/dev.sh test cpp",
      "group": "test", "problemMatcher": []
    },
    {
      "label": "배포: server + 서비스 재시작",
      "type": "shell", "command": "tools/dev.sh deploy server", "problemMatcher": []
    },
    {
      "label": "보드: python 디버그 서비스 ON",
      "type": "shell", "command": "tools/dev.sh debug py", "problemMatcher": []
    },
    {
      "label": "보드: python 디버그 서비스 OFF",
      "type": "shell", "command": "tools/dev.sh debug py --stop", "problemMatcher": []
    },
    {
      // isBackground: gdbserver 는 계속 떠 있으므로 태스크가 끝나기를 기다리면 안 된다.
      "label": "보드: gdbserver kc_test_motor_only",
      "type": "shell", "command": "tools/dev.sh debug cpp kc_test_motor_only",
      "isBackground": true,
      "problemMatcher": {
        "pattern": [{ "regexp": "^\\\\[dev\\\\](.*)\$", "file": 1, "location": 1, "message": 1 }],
        "background": {
          "activeOnStart": true,
          "beginsPattern": "gdbserver",
          "endsPattern": "Listening on port"
        }
      }
    },
    {
      "label": "보드: gdbserver test_cam_engine",
      "type": "shell", "command": "tools/dev.sh debug cpp test_cam_engine",
      "isBackground": true,
      "problemMatcher": {
        "pattern": [{ "regexp": "^\\\\[dev\\\\](.*)\$", "file": 1, "location": 1, "message": 1 }],
        "background": {
          "activeOnStart": true,
          "beginsPattern": "gdbserver",
          "endsPattern": "Listening on port"
        }
      }
    },
    {
      "label": "보드: gdbserver 정지",
      "type": "shell", "command": "tools/dev.sh debug stop", "problemMatcher": []
    },
    {
      "label": "보드: 상태 확인",
      "type": "shell", "command": "tools/dev.sh status", "problemMatcher": []
    }
  ]
}
EOF

    cat > "$ROOT/.vscode/settings.json" <<EOF
{
  // tools/dev.sh setup 이 생성함.
  // C/C++ 코드 추적은 clangd 가 담당한다(루트 compile_commands.json 기준).
  "clangd.path": "/usr/bin/clangd",
  "clangd.arguments": [
    "--background-index",
    "--compile-commands-dir=\${workspaceFolder}",
    "--header-insertion=never",
    "--clang-tidy"
  ],
  // clangd 와 MS IntelliSense 를 동시에 켜면 정의로 이동이 두 번 뜬다. 하나만 쓴다.
  "C_Cpp.intelliSenseEngine": "disabled",
  "cmake.configureOnOpen": false,

  // 파이썬 추적: server.* 임포트가 풀리도록 src/app 을 분석 경로에 넣는다.
  "python.defaultInterpreterPath": "\${workspaceFolder}/.venv/bin/python",
  "python.analysis.extraPaths": ["\${workspaceFolder}/src/app", "\${workspaceFolder}"],
  "python.analysis.autoImportCompletions": true,
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["-q"],
  "python.testing.cwd": "\${workspaceFolder}/src/app/server",
  "python.envFile": "\${workspaceFolder}/.vscode/.env",

  "files.associations": { "*.dts": "dts", "*.dtsi": "dts", "*.ld": "linkerscript" },
  "files.watcherExclude": {
    "**/build-*/**": true, "**/.venv/**": true, "**/node_modules/**": true
  },
  "search.exclude": {
    "**/build-*": true, "**/.venv": true, "**/node_modules": true,
    "**/compile_commands.json": true
  }
}
EOF

    # clangd 대신 MS C/C++ 확장을 쓰고 싶은 사람을 위한 설정.
    cat > "$ROOT/.vscode/c_cpp_properties.json" <<EOF
{
  "version": 4,
  "configurations": [
    {
      "name": "ortho-bender (compile_commands)",
      "compileCommands": "\${workspaceFolder}/compile_commands.json",
      "compilerPath": "/usr/bin/gcc",
      "cStandard": "c11",
      "cppStandard": "c++17",
      "intelliSenseMode": "linux-gcc-x64",
      "includePath": [
        "\${workspaceFolder}/src/shared",
        "\${workspaceFolder}/src/app/cam",
        "\${workspaceFolder}/src/app/ipc",
        "\${workspaceFolder}/src/firmware/**"
      ]
    }
  ]
}
EOF

    cat > "$ROOT/.vscode/extensions.json" <<'EOF'
{
  "recommendations": [
    "llvm-vs-code-extensions.vscode-clangd",
    "ms-vscode.cpptools",
    "ms-python.python",
    "ms-python.debugpy",
    "ms-vscode.cmake-tools",
    "anthropic.claude-code"
  ]
}
EOF

    grep -q OB_MOCK_MODE "$ROOT/.vscode/.env" 2>/dev/null || printf 'PYTHONPATH=${workspaceFolder}/src/app\nOB_MOCK_MODE=true\n' > "$ROOT/.vscode/.env"
    log ".vscode/{launch,tasks,settings,c_cpp_properties,extensions}.json 생성 (보드 $ip)"
}

# ─────────────────────────────────────────────────────────────
# test
# ─────────────────────────────────────────────────────────────

cmd_test() {
    local suite="${1:-py}"
    case "$suite" in
        py)
            # 파이썬 테스트는 두 군데에 흩어져 있고, 어느 한쪽만 돌리면 조용히 놓친다.
            #  - src/app/server/pytest.ini 는 testpaths=tests 라서 거기서 돌리면
            #    저장소 루트의 tests/*.py (모터 백엔드·드라이버·안전 테스트)를 통째로 뺀다.
            #  - 반대로 루트에서 인자 없이 pytest 를 돌리면 src/dev/*.py 를 수집하다
            #    spidev 가 없어서 수집 단계에서 죽는다.
            # 그래서 두 스위트를 명시적으로 각각 돌리고, 하나라도 깨지면 실패로 끝낸다.
            local rc=0
            step "pytest 1/2 — src/app/server (mock 모드, 하드웨어 불필요)"
            (cd "$ROOT/src/app/server" && OB_MOCK_MODE=true "$ROOT/.venv/bin/python" -m pytest -q) || rc=1
            step "pytest 2/2 — 저장소 루트 tests/"
            (cd "$ROOT" && OB_MOCK_MODE=true "$ROOT/.venv/bin/python" -m pytest -q tests) || rc=1
            (( rc == 0 )) || die "파이썬 테스트 실패 (위 두 스위트 중 하나 이상)"
            log "두 스위트 모두 통과" ;;
        py-server)
            step "pytest — src/app/server 만 (루트 tests/ 는 빠진다)"
            (cd "$ROOT/src/app/server" && OB_MOCK_MODE=true "$ROOT/.venv/bin/python" -m pytest -q) ;;
        py-root)
            step "pytest — tests/ (저장소 루트)"
            (cd "$ROOT" && OB_MOCK_MODE=true "$ROOT/.venv/bin/python" -m pytest -q tests) ;;
        cpp)
            step "ctest — 호스트 네이티브"
            cmd_build tests
            (cd "$ROOT/build-tests" && ctest --output-on-failure) ;;
        cpp-board)
            step "gtest — 크로스빌드해서 보드에서 실행"
            cmd_build tests-arm
            deploy_bin "$ROOT/build-tests-arm/test_cam_engine" "$ROOT/build-tests-arm/test_wire_materials"
            bssh "$BOARD_BIN/test_wire_materials && $BOARD_BIN/test_cam_engine" ;;
        safety)
            # 레지스터 기록 경로를 건드리기 전에 반드시 통과시켜야 하는 스위트.
            step "전류 안전 스위트 (CS≤19 / TOFF 1–8 / CHOPCONF 고정)"
            (cd "$ROOT/src/app/server" && OB_MOCK_MODE=true "$ROOT/.venv/bin/python" -m pytest -q tests/test_current_safety.py) ;;
        *) die "알 수 없는 스위트 '$suite' (py|py-server|py-root|cpp|cpp-board|safety)" ;;
    esac
}

# ─────────────────────────────────────────────────────────────
# deploy
# ─────────────────────────────────────────────────────────────

deploy_bin() {
    local f
    bssh "mkdir -p $BOARD_BIN"
    for f in "$@"; do
        [[ -f "$f" ]] || die "그런 바이너리가 없다: $f (먼저 빌드할 것)"
        log "-> $BOARD_BIN/$(basename "$f")"
        bscp "$f" "$(btgt):$BOARD_BIN/"
    done
    bssh "chmod +x $BOARD_BIN/*"
}

cmd_deploy() {
    local what="${1:-server}" ip; ip="$(board_ip)"
    case "$what" in
        server)
            step "server 배포 -> $ip:$BOARD_OPT/server"
            sshpass -p "$BOARD_PASS" rsync -az --delete \
                -e "ssh ${SSH_OPTS[*]}" \
                --exclude '__pycache__' --exclude '.pytest_cache' --exclude 'tests' \
                "$ROOT/src/app/server/" "$(btgt):$BOARD_OPT/server/"
            bssh "systemctl restart $PROD_UNIT"
            sleep 2
            bssh "systemctl is-active $PROD_UNIT"
            # 배포 성공 ≠ 반영. 트리 전체 md5 로 실제 일치를 확인한다.
            python3 "$ROOT/tools/check-board-sync.py" "$ip" || warn "보드가 체크아웃과 바이트 일치하지 않음" ;;
        docs)
            step "docs 배포 -> $ip:$BOARD_OPT/docs (재시작 불필요)"
            sshpass -p "$BOARD_PASS" rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
                "$ROOT/docs/sdk/" "$(btgt):$BOARD_OPT/docs/sdk/" ;;
        frontend)
            step "frontend 빌드 + 배포 -> $ip:$BOARD_OPT/frontend-dist"
            (cd "$ROOT/src/app/frontend" && npx tsc --noEmit -p tsconfig.json && npm run build)
            sshpass -p "$BOARD_PASS" rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
                "$ROOT/src/app/frontend/dist/" "$(btgt):$BOARD_OPT/frontend-dist/" ;;
        bin)
            step "크로스빌드 바이너리 배포 -> $ip:$BOARD_BIN"
            local bins=()
            for f in "$ROOT/build-kc-arm/kc_test_motor_only" \
                     "$ROOT/build-tests-arm/test_cam_engine" \
                     "$ROOT/build-tests-arm/test_wire_materials"; do
                [[ -f "$f" ]] && bins+=("$f")
            done
            ((${#bins[@]})) || die "aarch64 산출물이 없다 — tools/dev.sh build kc tests-arm"
            deploy_bin "${bins[@]}" ;;
        all) cmd_deploy server; cmd_deploy docs; cmd_deploy bin ;;
        *) die "알 수 없는 배포 대상 '$what' (server|docs|frontend|bin|all)" ;;
    esac
}

# ─────────────────────────────────────────────────────────────
# debug
# ─────────────────────────────────────────────────────────────

# 디버그 유닛은 운영 유닛에서 파생시킨다. 그래야 둘이 어긋나지 않는다.
# WorkingDirectory 와 Environment(OB_MOCK_MODE=false, spidev 백엔드, VimbaX GenTL 경로)를
# 그대로 물려받고 ExecStart 만 debugpy 로 감싼다.
write_debug_unit() {
    local wait_flag="$1"
    local unit
    unit="$(bssh "systemctl cat $PROD_UNIT")" || die "$PROD_UNIT 유닛 파일을 읽지 못함"
    local envs workdir
    # PATH 는 아래에서 따로 넣으므로 중복되지 않게 걸러낸다.
    envs="$(echo "$unit"  | grep -E '^Environment=' | grep -v '^Environment=PATH=' || true)"
    workdir="$(echo "$unit" | grep -E '^WorkingDirectory=' | head -1)"
    [[ -n "$workdir" ]] || workdir="WorkingDirectory=$BOARD_OPT"

    local wait_arg=""
    [[ "$wait_flag" == "--wait" ]] && wait_arg=" --wait-for-client"

    bssh "cat > /etc/systemd/system/$DEBUG_UNIT.service <<'UNIT'
[Unit]
Description=Ortho-Bender SDK Backend under debugpy (tools/dev.sh 생성)
Conflicts=$PROD_UNIT.service
After=network.target

[Service]
Type=simple
$workdir
Environment=PATH=/usr/sbin:/usr/bin:/sbin:/bin
$envs
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -m debugpy --listen 0.0.0.0:$DEBUGPY_PORT$wait_arg -m uvicorn server.main:app --host 0.0.0.0 --port 8000
Restart=no
StandardOutput=append:/var/log/ortho-backend-debug.log
StandardError=append:/var/log/ortho-backend-debug.log

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload"
}

debug_py() {
    local mode="${1:-}" ip; ip="$(board_ip)"
    case "$mode" in
        --stop)
            step "디버그 서비스 정지, $PROD_UNIT 복귀"
            bssh "systemctl stop $DEBUG_UNIT 2>/dev/null; systemctl start $PROD_UNIT; sleep 1; systemctl is-active $PROD_UNIT"
            log "보드가 정상 서비스로 돌아왔다" ;;
        --status)
            bssh "systemctl is-active $PROD_UNIT $DEBUG_UNIT 2>&1; $REMOTE_PORTS | grep -E ':($DEBUGPY_PORT|8000|$GDBSERVER_PORT)' || echo '(디버그 포트 리슨 없음)'" ;;
        *)
            bssh 'python3 -c "import debugpy" 2>/dev/null' || die "보드에 debugpy 가 없다. 실행: tools/dev.sh debug py --install"
            step "$DEBUG_UNIT 시작 ($ip, debugpy :$DEBUGPY_PORT)${mode:+ $mode}"
            write_debug_unit "$mode"
            # 두 유닛은 8000 포트를 공유하므로 운영 유닛을 먼저 내린다.
            bssh "systemctl stop $PROD_UNIT; systemctl restart $DEBUG_UNIT; sleep 2; systemctl is-active $DEBUG_UNIT"
            bssh "$REMOTE_PORTS | grep :$DEBUGPY_PORT || echo '(debugpy 포트가 아직 리슨하지 않음)'"
            echo
            log "VS Code 에서 붙기: 실행 및 디버그 -> 'PY · 보드 attach (debugpy $ip:$DEBUGPY_PORT)'"
            log "이제 src/app/server/**.py 의 중단점이 보드에서 멈춘다 ($BOARD_OPT/server 로 경로 매핑)"
            [[ "$mode" == "--wait" ]] && warn "--wait-for-client: attach 하기 전까지 API 는 응답하지 않는다"
            log "끝나면: tools/dev.sh debug py --stop" ;;
    esac
}

debug_py_install() {
    # 보드 시계가 수년 어긋나 있어 pip 의 TLS 인증서 검증이 실패한다.
    # 그래서 호스트에서 aarch64 휠을 받아 scp 로 넣고 오프라인 설치한다.
    step "보드에 debugpy 설치 (오프라인 휠)"
    local tmp; tmp="$(mktemp -d)"
    "$ROOT/.venv/bin/pip" download debugpy --no-deps --only-binary=:all: \
        --platform manylinux2014_aarch64 --python-version 3.10 --implementation cp --abi cp310 -d "$tmp" >/dev/null
    local whl; whl="$(ls "$tmp"/debugpy-*.whl | head -1)"
    bscp "$whl" "$(btgt):/tmp/"
    bssh "pip3 install --no-index --no-deps /tmp/$(basename "$whl") && python3 -c 'import debugpy;print(\"debugpy\", debugpy.__version__)'"
    rm -rf "$tmp"
}

debug_cpp() {
    local name="${1:-}"; shift || true
    [[ -n "$name" ]] || die "사용법: tools/dev.sh debug cpp <바이너리> [-- 인자...]"
    [[ "${1:-}" == "--" ]] && shift

    local local_bin="" cand
    for cand in "$ROOT/build-kc-arm/$name" "$ROOT/build-tests-arm/$name" "$ROOT/build-app-arm/$name"; do
        [[ -f "$cand" ]] && { local_bin="$cand"; break; }
    done
    if [[ -z "$local_bin" ]]; then
        case "$name" in
            kc_test*)  cmd_build kc;        local_bin="$ROOT/build-kc-arm/$name" ;;
            test_*)    cmd_build tests-arm; local_bin="$ROOT/build-tests-arm/$name" ;;
            *)         die "'$name' 이름의 aarch64 바이너리가 없다 — 먼저 빌드할 것" ;;
        esac
    fi
    [[ -f "$local_bin" ]] || die "$local_bin 이 여전히 없다"
    file "$local_bin" | grep -q aarch64 || die "$local_bin 은 aarch64 바이너리가 아니다"

    deploy_bin "$local_bin"
    local ip; ip="$(board_ip)"
    # 대괄호 트릭: pkill -f 는 자기 부모 셸의 명령줄까지 훑는다. 패턴을 그대로
    # 쓰면 이 SSH 세션의 셸이 패턴에 걸려 스스로 죽고 ssh 가 255 로 끊긴다.
    bssh "pkill -f '[g]dbserver.*:$GDBSERVER_PORT' 2>/dev/null; true"
    step "gdbserver $ip:$GDBSERVER_PORT -> $BOARD_BIN/$name $*"
    bssh "setsid gdbserver --once :$GDBSERVER_PORT $BOARD_BIN/$name $* > /tmp/gdbserver-$name.log 2>&1 < /dev/null &" || true
    sleep 1
    bssh "cat /tmp/gdbserver-$name.log" || true
    echo
    log "붙기: VS Code -> 'C++ · 보드 gdbserver attach' (심볼은 $local_bin 에서 읽음)"
    log "CLI:  gdb-multiarch -q $local_bin -ex 'set sysroot remote:/' -ex 'target remote $ip:$GDBSERVER_PORT'"
}

debug_stop() {
    bssh "pkill -f '[g]dbserver.*:$GDBSERVER_PORT' 2>/dev/null; true"
    log "gdbserver 정지"
}

cmd_debug() {
    local lane="${1:-}"; shift || true
    case "$lane" in
        py)   [[ "${1:-}" == "--install" ]] && { debug_py_install; return; }; debug_py "${1:-}" ;;
        cpp)  debug_cpp "$@" ;;
        stop) debug_stop ;;
        m7)
            step "M7 JTAG 디버그"
            [[ -f "$ROOT/build-firmware/ortho-bender-firmware.elf" ]] || die "펌웨어 ELF 없음 — tools/dev.sh build firmware"
            log "openocd -f interface/<프로브>.cfg -f target/imx8m.cfg"
            log "그 다음 VS Code -> 'M7 · JTAG (openocd + gdb-multiarch)'" ;;
        *) die "사용법: tools/dev.sh debug py|cpp|stop|m7" ;;
    esac
}

# ─────────────────────────────────────────────────────────────
# status / sync / clean / ip
# ─────────────────────────────────────────────────────────────

cmd_status() {
    local ip; ip="$(board_ip)"
    step "보드 $ip"
    curl -sf -o /dev/null -w "  /health          http %{http_code}  %{time_total}s\n" "http://$ip:8000/health" || echo "  /health          연결 실패"
    # systemctl is-active 는 비활성일 때도 'inactive' 를 stdout 에 찍고 3 으로 끝난다.
    # '|| echo' 를 덧붙이면 값이 두 줄이 되어 printf 형식이 재사용되므로 head -1 로 자른다.
    bssh "printf '  %-16s %s\n' '서비스' \"\$(systemctl is-active $PROD_UNIT | head -1)\"
          printf '  %-16s %s\n' '디버그 서비스' \"\$(systemctl is-active $DEBUG_UNIT 2>/dev/null | head -1)\"
          printf '  %-16s %s\n' '보드 시계' \"\$(date -u)\"
          printf '  %-16s %s\n' 'debugpy' \"\$(python3 -c 'import debugpy;print(debugpy.__version__)' 2>/dev/null || echo '미설치')\"
          printf '  %-16s %s\n' 'gdbserver' \"\$(command -v gdbserver || echo 없음)\"
          echo '  리슨 중인 포트:'; $REMOTE_PORTS | grep -E ':(8000|$DEBUGPY_PORT|$GDBSERVER_PORT)' | sed 's/^/    /' || echo '    (없음)'"
    echo "  ${c_dim}보드 시계는 수년 어긋나 있다. 로그를 호스트 측정과 시간으로 대조하지 말 것.${c_off}"
    step "호스트 빌드 트리"
    for d in build-app build-app-arm build-tests build-tests-arm build-kc-arm build-firmware; do
        if [[ -d "$ROOT/$d" ]]; then
            printf '  %-18s %s\n' "$d" "$(grep -m1 CMAKE_BUILD_TYPE:STRING "$ROOT/$d/CMakeCache.txt" 2>/dev/null | cut -d= -f2)"
        else
            printf '  %-18s %s\n' "$d" "-"
        fi
    done
}

cmd_sync() { python3 "$ROOT/tools/check-board-sync.py" "$(board_ip)"; }

cmd_clean() {
    step "빌드 트리 제거"
    rm -rf "$ROOT"/build-app "$ROOT"/build-app-arm "$ROOT"/build-tests \
           "$ROOT"/build-tests-arm "$ROOT"/build-kc-arm "$ROOT"/build-firmware
    log "클린 완료. 다음 빌드는 전체 빌드다."
}

cmd_ip() {
    local ip; ip="$(board_ip)"
    echo "$ip"
    if [[ "${1:-}" == "--write" ]]; then
        echo "$ip" > "$ROOT/.board-ip"; gen_vscode
    fi
}

usage() { sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; }

case "${1:-help}" in
    setup)  shift; cmd_setup "$@" ;;
    build)  shift; cmd_build "$@" ;;
    test)   shift; cmd_test "$@" ;;
    deploy) shift; cmd_deploy "$@" ;;
    debug)  shift; cmd_debug "$@" ;;
    status) shift; cmd_status "$@" ;;
    sync)   shift; cmd_sync "$@" ;;
    clean)  shift; cmd_clean "$@" ;;
    ip)     shift; cmd_ip "$@" ;;
    vscode) shift; gen_vscode ;;
    compdb) shift; gen_compdb ;;
    help|-h|--help) usage ;;
    *) usage; exit 1 ;;
esac
