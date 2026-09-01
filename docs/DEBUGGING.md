# 빌드 · 배포 · 디버깅

모든 조작은 `tools/dev.sh` 하나로 들어간다. VS Code 의 태스크/디버그 구성도
전부 이 스크립트를 호출한다.

```bash
tools/dev.sh setup          # 툴체인 점검 + .clangd + .vscode + compile_commands.json 생성
tools/dev.sh status         # 보드 상태(서비스/포트/시계) + 호스트 빌드 트리 상태
```

`setup` 이 만드는 파일(`.clangd`, `.vscode/*`, `compile_commands.json`)은
`.gitignore` 대상이라 커밋되지 않는다. 언제든 다시 만들면 된다.

---

## 0. 폴더는 WSL 안에서 열 것

코드는 Ubuntu 안에서 실행된다 — cmake, sshpass, `.venv`, 보드 스크립트가
전부 거기에 있다. Windows 쪽 VS Code 로 `\\wsl.localhost\...` 경로를 열면
태스크는 (내부적으로 `wsl.exe` 를 거치므로) 돌아가지만, **clangd·파이썬
인터프리터·로컬 디버거는 공유 경로 너머의 리눅스 툴체인에 닿지 못한다.**

> `Ctrl+Shift+P` → **WSL: Reopen Folder in WSL**

아래 네 레인은 전부 이 전제 위에 서 있다. 이걸 건너뛰면 태스크는 도는데
중단점이 안 걸리는, 원인 찾기 어려운 상태가 된다.

---

## 1. 디버깅 레인 4개

| 레인 | 대상 | 실제로 도는 곳 | 상태 |
|---|---|---|---|
| PY | FastAPI 백엔드 | 보드 (aarch64) | **검증됨** |
| C++ 보드 | 크로스빌드 바이너리 | 보드 (aarch64) | **검증됨** |
| C++ 호스트 | gtest | 개발 PC | **검증됨** |
| M7 | FreeRTOS 펌웨어 | M7 코어 | 빌드 준비만 — SDK·JTAG 필요 |

빌드는 기본이 `-O0 -g3 -fno-omit-frame-pointer -fno-inline` 이다.
최적화 빌드에서는 중단점이 엉뚱한 줄로 밀리므로, 디버깅할 물건에
`--release` 를 쓰지 말 것.

---

## 2. PY — 보드에서 도는 백엔드에 붙기

보드에서 실제로 일을 하는 것은 FastAPI 서버다. 여기에 붙는 게 기본 작업 흐름이다.

```bash
tools/dev.sh debug py            # 디버그 서비스로 교체 (debugpy :5678)
#   VS Code → 실행 및 디버그 → "PY · 보드 attach (debugpy <ip>:5678)"
#   src/app/server/**.py 에 중단점을 찍고 API 를 때리면 그 줄에서 멈춘다
tools/dev.sh debug py --stop     # 원래 서비스로 복귀  ← 끝나면 반드시
```

동작 방식:

- 운영 유닛 `ortho-bender-sdk` 를 읽어 `WorkingDirectory` 와 `Environment`
  (`OB_MOCK_MODE=false`, `OB_MOTOR_BACKEND=spidev`, VimbaX GenTL 경로)를 그대로
  물려받은 `ortho-bender-sdk-debug` 를 만든다. 실행줄만 `debugpy` 로 감싼다.
  두 유닛은 `Conflicts=` 로 묶여 있어 동시에 뜨지 않는다.
- 경로 매핑: 호스트 `src/app/server` ↔ 보드 `/opt/ortho-bender/server`.
  중단점을 호스트 파일에 찍어도 보드에서 잡히고, 콜 스택도 호스트 경로로 돌아온다.

주의할 점:

- **기동이 느리다.** pydevd 가 임포트마다 추적을 걸어서, `:8000` 이 응답하기까지
  평소 7초가 **40–60초**로 늘어난다. 죽은 게 아니다. 기다릴 것.
- `--wait` 를 주면 `--wait-for-client` 가 붙는다. attach 하기 전까지 API 가
  아예 응답하지 않으니, 기동 코드(`main.py` 의 lifespan)를 디버깅할 때만 쓴다.
- 보드 시계가 수년 어긋나 있어 `pip` 의 TLS 인증서 검증이 실패한다. 그래서
  `tools/dev.sh debug py --install` 은 호스트에서 aarch64 휠을 받아 scp 로
  넣고 오프라인 설치한다. (현재 보드에 debugpy 1.8.21 설치 완료.)

로그는 `/var/log/ortho-backend-debug.log` 로 따로 떨어진다.

## 3. C++ — 보드에서 gdbserver 로 붙기

```bash
tools/dev.sh build kc tests-arm          # aarch64 크로스빌드
tools/dev.sh debug cpp kc_test_motor_only    # 배포 + gdbserver :2345 기동
tools/dev.sh debug cpp test_cam_engine       # gtest 바이너리로도 가능
#   VS Code → "C++ · 보드 gdbserver attach — ..."
tools/dev.sh debug stop
```

심볼은 보드가 아니라 **호스트의 크로스빌드 산출물**에서 읽는다. 보드에는
스트립하지 않은 바이너리만 올라가고, 소스는 호스트 경로 그대로 열린다.

CLI 로 붙을 때:

```bash
gdb-multiarch -q build-tests-arm/test_cam_engine \
  -ex 'set sysroot remote:/' \
  -ex 'target remote <ip>:2345'
```

`set sysroot remote:/` 는 보드 쪽 공유 라이브러리를 gdb 연결로 끌어온다.
처음 붙을 때 수십 초 걸리지만, 호스트/보드 라이브러리 버전이 달라서 생기는
심볼 불일치를 없애 준다.

크로스 빌드 gtest 는 `/usr/src/googletest` 소스를 타깃 툴체인으로 같이 빌드한다
(`sudo apt install googletest`). 네트워크가 필요 없다.

`aarch64-linux-gnu-*` 대신 Yocto SDK 를 쓰면 보드와 동일한 sysroot 로 빌드된다.
SDK 환경을 source 한 뒤 그대로 `tools/dev.sh build` 를 부르면 툴체인 파일이
자동으로 SDK 쪽을 잡는다.

## 4. C++ — 호스트에서 gtest 디버깅

```bash
tools/dev.sh build tests
tools/dev.sh test cpp
#   VS Code → "C++ · 호스트 gtest: cam_engine"
```

하드웨어가 필요 없는 알고리즘(B-code 생성, 스프링백 보정, 와이어 재질 테이블)은
여기서 잡는 게 제일 빠르다.

## 5. M7 펌웨어

지금 **빌드가 되지 않는다.** MCUXpresso SDK 가 이 PC 에 없다.

```bash
OB_M7_SDK=/경로/m7_sdk tools/dev.sh build firmware
```

SDK 가 생기면 위 명령으로 빌드되고, `compile_commands.json` 에 펌웨어 항목이
합쳐지면서 clangd 의 FreeRTOS/SDK 헤더 오류도 사라진다.

JTAG 디버깅에는 프로브가 추가로 필요하다. `openocd` 와 `gdb-multiarch` 는
설치돼 있고, `target/imx8m.cfg` 도 있다. `launch.json` 의
"M7 · JTAG" 구성에서 `interface/jlink.cfg` 를 실제 프로브 설정으로 바꾸면 된다.
(우분투 22.04 에는 `arm-none-eabi-gdb` 패키지가 없다. `gdb-multiarch` 에
`set architecture armv7e-m` 으로 쓴다 — launch 구성에 이미 들어가 있다.)

---

## 6. 코드/함수 추적

C/C++ 는 clangd, 파이썬은 Pylance 가 담당한다.

- `tools/dev.sh setup` 이 빌드 트리 5개의 `compile_commands.json` 을 저장소
  루트 하나로 합친다. 네이티브 빌드를 먼저 넣는데, clangd 는 한 파일에 대해
  처음 만난 항목을 쓰고 x86 clang 이 해석할 수 있는 건 네이티브 플래그이기
  때문이다.
- 컴파일 DB 에 없는 펌웨어 `.c` 는 clangd 가 근처 C++ 항목의 플래그를 빌려 쓰다
  `-x c++` 로 열려 버린다. `.clangd` 에서 `-xc` 로 언어를 못 박아 막았다.
- 파이썬은 `.vscode/settings.json` 의 `python.analysis.extraPaths` 에
  `src/app` 이 들어가 있어 `server.*` 임포트가 풀린다.

지금 상태에서 정의로 이동이 깨끗하게 되는 범위: `src/app/cam`, `src/app/ipc`,
`src/shared`, `tests`, `tools/kc_port`, 그리고 SDK 헤더를 물지 않는 펌웨어 파일.
`src/firmware/source/main.c` 처럼 FreeRTOS 헤더를 직접 include 하는 파일은
SDK 가 들어오기 전까지 그 헤더만 못 찾는다.

---

## 7. 빌드·배포

```bash
tools/dev.sh build all --clean      # 전체 클린 빌드 (app/tests/app-arm/tests-arm/kc)
tools/dev.sh build app --release    # 최적화 빌드
tools/dev.sh test py                # 파이썬 두 스위트 전부, 하드웨어 불필요
tools/dev.sh test safety            # 전류 안전 스위트 (레지스터 건드리기 전 필수)
tools/dev.sh test cpp-board         # 크로스빌드 gtest 를 보드에서 실행

tools/dev.sh deploy server          # rsync + 재시작 + md5 동기화 검증
tools/dev.sh deploy docs            # 재시작 불필요
tools/dev.sh deploy frontend        # tsc + vite build 후 배포
tools/dev.sh deploy bin             # 크로스빌드 바이너리 → /opt/ortho-bender/bin
```

`deploy server` 는 배포 후 `tools/check-board-sync.py` 로 트리 전체 md5 를
대조한다. **배포 성공은 반영을 뜻하지 않는다** — 이 대조가 실제 확인이다.

### 파이썬 테스트는 두 디렉터리에 있다 — 루트에서 돌릴 것

테스트는 저장소 루트 `tests/` (모터 백엔드, TMC 드라이버, SPI 안전)와
`src/app/server/tests/` 두 군데에 있다. PR #49 로 **저장소 루트에
`pytest.ini`** 가 생겼고 그 `testpaths` 가 둘 다 지정하므로, 루트에서
인자 없이 `pytest` 한 번이면 전체 집합이다. `tools/dev.sh test py` 와
CI 가 하는 것도 정확히 그것이다.

닫히지 않은 함정이 하나 남아 있다. **`testpaths` 는 rootdir 에서 실행할
때만 적용된다**(pytest 의 문서화된 동작). 그래서

```bash
cd src/app/server && pytest      # 여전히 부분 실행 — 루트 tests/ 가 빠진다
```

는 지금도 절반만 돈다. #49 이전과 이유가 다르다 — 예전에는 중첩된
`src/app/server/pytest.ini` 가 범위를 좁혔고(그 파일은 #49 가 삭제했다),
지금은 rootdir 밖에서 실행해 `testpaths` 자체가 적용되지 않기 때문이다.
**저장소 루트에서 돌리거나 `tools/dev.sh test py` 를 쓸 것.**

한쪽만 따로 보고 싶을 때만 `test py-server` / `test py-root` 를 쓴다.
진단용이며, 이 둘의 결과로 "통과"를 판단하지 않는다.

## 8. 단축키 제안

사용자 `keybindings.json` 에 추가한다 (`Ctrl+Shift+P` → *Preferences: Open
Keyboard Shortcuts (JSON)*). `args` 는 `tools/dev.sh setup` 이 생성하는
`.vscode/tasks.json` 의 레이블과 글자 단위로 일치해야 한다:

```json
[
  { "key": "ctrl+alt+d", "command": "workbench.action.tasks.runTask",
    "args": "배포: server + 서비스 재시작" },
  { "key": "ctrl+alt+s", "command": "workbench.action.tasks.runTask",
    "args": "보드: 상태 확인" },
  { "key": "ctrl+alt+t", "command": "workbench.action.tasks.runTask",
    "args": "테스트: python (mock)" },
  { "key": "ctrl+alt+p", "command": "workbench.action.tasks.runTask",
    "args": "보드: python 디버그 서비스 ON" }
]
```

기본 그룹 단축키는 이미 배선돼 있다 — `Ctrl+Shift+B` 는 "빌드: tests
(Debug)", *Run Test Task* 는 "테스트: python (mock)" 이 기본이다.

디버그 서비스를 켰으면(`ctrl+alt+p`) 끝나고 반드시 "보드: python 디버그
서비스 OFF" 를 실행할 것 — debugpy 아래에서는 백엔드 기동이 40–60 초라,
켠 채 잊으면 다음 사람이 죽은 보드로 오인한다.

---

## 9. 보드 IP

IP 는 움직인다. `tools/dev.sh` 는 `.board-ip` 캐시의 **:22(SSH)** 가 열려 있는지로
판정하고, 닫혀 있으면 `tools/find-board.py` 로 다시 찾는다. `:8000` 을 기준으로
삼지 않는 이유는, 백엔드가 잠깐 내려가 있을 때 배포·gdbserver 같은 SSH 작업까지
전부 막히기 때문이다.

```bash
tools/dev.sh ip --write     # 현재 IP 를 .board-ip 에 쓰고 launch.json 재생성
OB_BOARD_IP=10.0.0.5 tools/dev.sh status    # 일회성 지정
```

`launch.json` 에는 생성 시점의 IP 가 박힌다. IP 가 바뀌면
`tools/dev.sh setup` 또는 `tools/dev.sh vscode` 를 다시 실행할 것.
