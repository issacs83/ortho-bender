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

### 파이썬 테스트는 두 군데에 있다

`tools/dev.sh test py` 가 **두 스위트를 모두** 돌리는 이유:

- `src/app/server/pytest.ini` 에 `testpaths = tests` 가 있어서, 그 디렉터리에서
  pytest 를 돌리면 저장소 루트의 `tests/*.py` (모터 백엔드, TMC 드라이버,
  SPI 안전 테스트)를 **통째로 건너뛴다.** 조용히 빠지므로 눈치채기 어렵다.
- 반대로 저장소 루트에서 인자 없이 `pytest` 를 돌리면 `src/dev/*.py` 를
  수집하다가 `spidev` 가 없어 **수집 단계에서 죽는다.**

한쪽만 보고 싶으면 `test py-server` / `test py-root` 를 쓴다.

## 8. 보드 IP

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
