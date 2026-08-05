# src/dev 문제점 분석 보고서

작성일: 2026-05-08  
대상: `/home/issacs/work/quarkers/ortho-bender/src/dev/`

## 1. 요약

`src/dev`는 i.MX8MP EVK + Veyron/DRI0035/TMC 계열 모터 벤치에서 DTS를 직접 수정하고, Python으로 SPI/PWM/GPIO를 제어하기 위한 실험용 작업 디렉터리다. 현재 가장 큰 문제는 DTS 토폴로지와 Python 스크립트의 전제가 서로 섞여 있다는 점이다.

현재 파일들은 크게 세 가지 전제를 동시에 가지고 있다.

- `1-CS + manual CS`: `/dev/spidev1.0`만 사용하고 `SPI_NO_CS`로 커널 CS 토글을 막은 뒤 Python이 모든 CS GPIO를 직접 토글
- `1-CS + mixed manual/native`: FEED/LIFT는 native 또는 기존 spidev, BEND만 manual GPIO CS
- `3-CS native`: `/dev/spidev1.0`, `/dev/spidev1.1`, `/dev/spidev1.2`가 각각 FEED/BEND/LIFT에 매핑된다고 가정

이 전제가 실제 보드에 올라간 DTB와 맞지 않으면 스크립트가 즉시 실패하거나, 더 위험하게는 의도하지 않은 모터 드라이버를 동시에 선택할 수 있다.

## 2. 파일 현황

### DTS 계열

| 파일 | 성격 | 주요 상태 |
|------|------|-----------|
| `dtb_current.dts` | 현재/복원 기준처럼 보이는 DTS | `dtb_restore.dts`와 완전히 동일 |
| `dtb_restore.dts` | 복원용처럼 보이는 DTS | `dtb_current.dts`와 SHA256 동일, 실제 stock 여부 불명 |
| `dtb_manual_no_csgpios.dts` | manual CS 실험판 | `dtb_current.dts`에서 `cs-gpios`만 제거 |
| `dtb_active.dts` | native 3-CS 실험판 | `num-cs=3`이지만 `fsl,spi-num-chipselects=1`, CS 매핑 오류 있음 |

### Python 계열

| 파일 | 의도 | 주요 전제 |
|------|------|-----------|
| `motor_chip.py` | 단일 칩 수동 CS 구동 | `SPI_NO_CS` + FEED/BEND/LIFT 모두 manual GPIO CS |
| `motor_bend_manual.py` | BEND 수동 CS 단일 구동 | `SPI_NO_CS` + BEND manual CS |
| `motor_chip_only.py` | 단일 칩 테스트 | mixed 방식, `SPI_NO_CS` 없음 |
| `motor_all3_phase1.py` | 3축 phase1 구동 | mixed 방식, BEND manual CS지만 `SPI_NO_CS` 없음 |
| `motor_all3_native.py` | 3축 native CS 동시 구동 | `/dev/spidev1.0/1.1/1.2` 필요 |
| `motor_bend_native.py` | BEND native CS 단일 구동 | `/dev/spidev1.1` 필요 |
| `motor_seq_native.py` | 3축 native CS 순차 구동 | `/dev/spidev1.0/1.1/1.2` 필요 |

## 3. 치명/상급 문제

### 3.1 `dtb_active.dts`의 SPI CS 수 불일치

위치:

- `dtb_active.dts`: `spi@30830000`
- `fsl,spi-num-chipselects = <0x01>;`
- `num-cs = <0x03>;`

문제:

`num-cs`는 3개로 늘렸지만 `fsl,spi-num-chipselects`는 1개로 남아 있다. 문서의 트러블슈팅 항목에 적힌 `cs1 >= max 1` 조건과 일치한다. 이 상태에서는 `spidev@1`, `spidev@2`가 정상 등록되지 않거나 SPI core/driver probe 단계에서 실패할 수 있다.

영향:

- `motor_all3_native.py`
- `motor_bend_native.py`
- `motor_seq_native.py`

권장 조치:

- native 3-CS를 사용할 경우 `fsl,spi-num-chipselects = <0x03>;`로 맞춘다.
- manual CS 통일 구성을 사용할 경우 `dtb_active.dts`를 사용하지 않고 `num-cs=1` 구성으로 정리한다.

### 3.2 `dtb_active.dts`의 BEND CS GPIO 매핑 오류

위치:

```dts
cs-gpios = <0x29 0x0d 0x01 0x29 0x1d 0x01 0x29 0x07 0x01>;
```

문제:

phandle `0x29`는 `gpio@30240000`, 즉 GPIO5다. 따라서 두 번째 CS는 `gpio5_29`가 된다. 하지만 문서와 Python 스크립트에서 BEND CS는 `gpio3_22`로 사용되고 있다.

영향:

- `/dev/spidev1.1`이 BEND라고 가정하는 native 스크립트가 실제 BEND CS를 토글하지 못할 가능성이 높다.
- 잘못된 GPIO를 건드릴 수 있다.

권장 조치:

native 3-CS 구성이 목표라면 두 번째 entry는 최소한 다음 의도에 맞게 재검토해야 한다.

```dts
cs-gpios = <0x29 0x0d 0x01 0x2a 0x16 0x01 0x29 0x07 0x01>;
```

단, 이 경우에도 해당 pad가 pinctrl에서 GPIO로 잡혀 있고 다른 드라이버와 충돌하지 않는지 확인해야 한다.

### 3.3 motorbench pinctrl과 `micfil`/`pdmgrp` pinctrl 충돌

위치:

- `dtb_current.dts` / `dtb_manual_no_csgpios.dts` / `dtb_restore.dts`
- `pdmgrp`: `0x130`, `0x138`, `0x13c`, `0x140`
- `motorbenchstepdirgrp`: `0x138`, `0x140`, `0x1e0`, `0x1e4`
- `motorbenchestopgrp`: `0x130`, `0x1e8`
- `micfil@30ca0000`: `status = "okay";`, `pinctrl-0 = <0x70>;`

문제:

`micfil`이 `pdmgrp`를 통해 SAI5 계열 pad를 오디오 입력으로 claim하고 있고, motorbench도 같은 pad들을 GPIO로 claim한다. 같은 pad가 두 pinctrl group에 동시에 들어가면 probe 순서에 따라 pinctrl 적용 실패가 발생할 수 있다.

영향:

- `spi_imx 30830000.spi: Error applying setting, reverse things back`
- 모터 벤치 SPI/PWM/GPIO가 부팅 중 적용되지 않을 수 있음
- 부팅마다 증상이 달라질 수 있음

권장 조치:

- 모터 벤치 DTB에서는 `micfil@30ca0000`을 `status = "disabled";`로 내린다.
- 또는 `pdmgrp`에서 모터 벤치가 쓰는 SAI5 pad를 제거한다.
- 정식 DTS 소스에서도 같은 충돌이 재발하지 않게 반영한다.

### 3.4 `dtb_active.dts`의 UART1 pinctrl 충돌 가능성

위치:

- `dtb_active.dts`
- `motorbenchstepdirgrp`: `0x224 ... alt5`
- `uart1grp`: `0x224 ... alt0`
- `serial@30860000`: `status = "okay";`

문제:

`0x224` pad가 UART1과 motorbench GPIO 양쪽에서 사용된다. UART1이 활성 상태라면 motorbench가 같은 pad를 GPIO로 다시 claim하려고 할 때 충돌한다.

권장 조치:

- `0x224`를 motorbench에서 제거하거나,
- UART1을 비활성화하고 console 영향까지 검토한다.

## 4. Python 스크립트 문제

### 4.1 mixed manual CS 스크립트에서 `SPI_NO_CS` 누락

대상:

- `motor_all3_phase1.py`
- `motor_chip_only.py`

문제:

두 스크립트는 BEND를 manual GPIO CS로 내리면서 SPI 전송은 `spidev1.0`으로 수행한다. 그런데 `SPI_NO_CS`를 설정하지 않는다. 이 경우 커널이 FEED native CS를 토글하면서 동시에 Python이 BEND CS를 내릴 수 있다.

영향:

- FEED와 BEND가 동시에 선택될 수 있음
- SPI MISO 충돌 또는 잘못된 레지스터 write 가능
- 모터가 의도와 다르게 동작할 수 있음

권장 조치:

- mixed/manual 방식에서는 `motor_bend_manual.py`처럼 `SPI_NO_CS` ioctl을 반드시 적용한다.
- 더 좋은 방향은 `motor_chip.py`처럼 모든 CS를 manual 방식으로 통일하는 것이다.

### 4.2 native 스크립트는 현재 `dtb_current`와 호환되지 않음

대상:

- `motor_all3_native.py`
- `motor_bend_native.py`
- `motor_seq_native.py`

문제:

이 스크립트들은 `/dev/spidev1.1`과 `/dev/spidev1.2`가 존재한다고 가정한다. 하지만 `dtb_current.dts`는 `num-cs=1`, `cs-gpios`도 1개이므로 정상 상태에서는 `/dev/spidev1.0`만 기대해야 한다.

영향:

- `spi.open(1, 1)` 또는 `spi.open(1, 2)`에서 실패
- `dtb_active.dts`를 적용해도 현재 CS 수/매핑 문제가 있어 정상 동작을 보장하기 어려움

권장 조치:

- native 스크립트는 `dtb_active`가 고쳐진 뒤에만 사용하도록 문서에 명시한다.
- 현재 벤치 기준 스크립트를 manual 계열로 정하고, native 계열은 `legacy/` 또는 `experiments/`로 분리한다.

### 4.3 PWM 경로 하드코딩

대상:

- 모든 Python 스크립트

문제:

모든 스크립트가 `/sys/class/pwm/pwmchip2/pwm0`을 고정으로 사용한다. 문서상 현재 환경에서는 맞을 수 있지만, 커널/DTB/driver probe 순서에 따라 `pwmchip` 번호는 바뀔 수 있다.

영향:

- 다른 이미지나 부팅 상태에서 PWM export 실패
- 잘못된 PWM chip 제어 가능성

권장 조치:

- `/sys/class/pwm/pwmchip*/device/of_node` 또는 `uevent`를 보고 `30690000.pwm`에 해당하는 pwmchip을 찾아 사용한다.
- 최소한 실행 전 `pwmchip2`가 `pwm@30690000`인지 검증하는 guard를 추가한다.

### 4.4 예외 발생 시 GPIO/SPI/PWM cleanup이 불완전한 스크립트

대상:

- `motor_chip.py`

문제:

이 스크립트는 대부분의 초기화와 구동 로직이 top-level에서 실행되고, 전체 `try/finally`로 감싸져 있지 않다. 중간 예외나 Ctrl-C 시 PWM disable, CS idle, GPIO release가 누락될 수 있다.

권장 조치:

- `main()` 구조로 옮기고 전체 하드웨어 사용 구간을 `try/finally`로 감싼다.
- `SIGINT`, `SIGTERM` 모두 처리한다.

## 5. 문서 문제

### 5.1 컴파일 후 push 원라이너의 성공 경로 오류

위치:

```bash
dtc -I dts -O dtb -o new.dtb current.dts 2>&1 | grep -i error && \
    scp new.dtb ...
```

문제:

`grep -i error`는 에러가 없을 때 exit code 1을 반환한다. 따라서 DTB 컴파일이 성공하면 `scp`와 `reboot`가 실행되지 않는다. 반대로 error 문자열이 출력될 때 뒤 명령이 실행될 수 있다.

권장 조치:

```bash
dtc -I dts -O dtb -o new.dtb current.dts && \
    scp new.dtb root@192.168.77.2:/run/media/boot-mmcblk2p1/imx8mp-ortho-bender-bench.dtb && \
    ssh root@192.168.77.2 "sync; /sbin/reboot"
```

경고를 보고 싶다면 `dtc` output을 로그 파일에 저장한 뒤 exit code로 판단한다.

### 5.2 `dtb_restore.dts`가 restore 기준으로 보이지 않음

문제:

`dtb_restore.dts`와 `dtb_current.dts`는 SHA256이 동일하다. 파일명만 보면 stock/restore 기준처럼 보이지만 실제 내용은 current와 같다.

권장 조치:

- 진짜 stock decompile 결과는 `dtb_stock.dts` 또는 `stock.dts`로 명명한다.
- `dtb_restore.dts`는 삭제하거나 정확한 의미를 문서화한다.

### 5.3 문서의 "현재 setup"과 파일 상태 불일치

문제:

문서는 Case A에서 `cs-gpios` 제거 + `SPI_NO_CS` + 모든 CS manual toggle을 "현재 setup"으로 설명한다. 하지만 `dtb_current.dts`에는 `cs-gpios = <0x29 0x0d 0x01>;`가 남아 있고, 모든 Python 스크립트가 manual 통일 방식인 것도 아니다.

권장 조치:

- 문서 첫 부분에 "현재 보드에 적용된 DTB"를 명확히 기록한다.
- 각 Python 스크립트가 요구하는 DTB variant를 표로 고정한다.

## 6. 권장 정리 방향

### 우선순위 1: 기준 토폴로지 결정

현 상태에서 가장 안전한 선택지는 `manual CS 통일`이다.

권장 기준:

- ECSPI2는 `/dev/spidev1.0` 하나만 사용
- `SPI_NO_CS`를 항상 적용
- FEED/BEND/LIFT CS는 모두 Python/gpiod에서 직접 토글
- 실행 스크립트는 `motor_chip.py` 계열로 통일

### 우선순위 2: DTS 충돌 제거

manual CS 기준이라도 pinctrl 충돌은 별도로 제거해야 한다.

- `micfil@30ca0000` 비활성화
- motorbench가 쓰는 pad와 `pdmgrp`, `uart1grp`, `uart3grp` 충돌 제거
- `dtb_manual_no_csgpios.dts`를 기준 후보로 삼되, `cs-gpios` 제거만으로 충분한지 실제 `/dev/spidev1.0` 생성 여부 확인

### 우선순위 3: 실험 파일 분리

추천 구조:

```text
src/dev/
  HANDOFF_DTS_WORKFLOW.md
  DEV_ISSUES_REPORT.md
  dts/
    manual-cs.dts
    native-3cs.dts
    stock.dts
  scripts/
    motor_chip_manual.py
    motor_bend_manual.py
  experiments/
    motor_all3_native.py
    motor_seq_native.py
    motor_all3_phase1.py
```

### 우선순위 4: 정식 Yocto DTS와 동기화

`src/dev`의 decompiled DTS 직접 수정은 벤치 실험에는 빠르지만, 정식 빌드 소스와 분리되어 있다. 최종적으로는 다음 소스에 반영해야 한다.

- `meta-ortho-bender/recipes-bsp/linux/linux-imx/dts/imx8mp-ortho-bender-motors.dtsi`
- 필요 시 bench 전용 DTS/DTSI 추가

## 7. 즉시 확인 체크리스트

보드에서 다음을 먼저 확인한다.

```bash
ls /dev/spidev*
ls /sys/class/pwm/
dmesg | grep -iE 'spi_imx|pinctrl|cs[0-9]|error|fail' | tail -50
cat /sys/kernel/debug/pinctrl/30330000.pinctrl/pinmux-pins | grep -E 'motorbench|micfil|uart'
```

판단 기준:

- `/dev/spidev1.0`만 있으면 manual CS 계열만 실행
- `/dev/spidev1.0`, `1.1`, `1.2`가 있어도 `dtb_active.dts`의 CS 매핑을 고치기 전에는 native 계열 실행 금지
- pinctrl log에 `Error applying setting`이 있으면 DTS 충돌 제거가 먼저

## 8. 결론

현재 문제는 개별 Python 문법 오류보다 DTS/스크립트 토폴로지 불일치가 본질이다. 특히 `dtb_active.dts`의 CS 수 불일치와 BEND CS 오매핑, `micfil`과 motorbench의 SAI5 pad 충돌, mixed manual CS 스크립트의 `SPI_NO_CS` 누락이 가장 위험하다.

가장 빠른 안정화 경로는 manual CS 통일 구성으로 기준을 정하고, 그 기준과 맞지 않는 native 실험 파일을 분리한 뒤, DTS에서 `micfil`/UART/pdm pinctrl 충돌을 제거하는 것이다.

## 9. 추가 런타임 확인 결과

확인 시점: 2026-05-08 22시대  
보드 상태: `micfil@30ca0000` disabled 적용 후

### 9.1 현재 보드 DTB 상태

확인 결과:

- `/dev/spidev1.0`만 존재
- `/sys/class/pwm/pwmchip2`는 `30690000.pwm`, 즉 PWM4로 확인
- `dmesg`에는 여전히 다음 에러가 있음

```text
spi_imx 30830000.spi: cs1 >= max 1
spi_master spi1: Failed to create SPI device for .../spidev@1
spi_imx 30830000.spi: cs2 >= max 1
spi_master spi1: Failed to create SPI device for .../spidev@2
```

판단:

현재 보드는 사실상 `1-CS + manual CS` 구성인데, DTS 안에 `spidev@1`과 `spidev@2` child가 아직 enabled 상태라서 부팅 중 등록 실패가 난다. `/dev/spidev1.0` 자체는 생기므로 FEED/LIFT manual CS 진단은 가능하지만, DTS는 깨끗한 상태가 아니다.

조치:

- `current.dts`에서 `spidev@1`, `spidev@2`에 `status = "disabled";` 추가

### 9.2 SPI write/readback 검증

`spi_writeverify.py`로 PWM 없이 RDSEL 변경 readback을 확인했다.

| 대상 | CS line | 결과 | 판단 |
|------|---------|------|------|
| FEED | `gpio5_13` | RDSEL별 readback 변화 있음 | SPI write 정상 |
| BEND | `gpio3_22` | 항상 `0x00000` | BEND 칩 응답 없음 |
| LIFT | `gpio5_7` | RDSEL별 readback 변화 있음 | SPI write 정상 |

BEND는 active-high CS로도 시험했지만 계속 `0x00000`이었다. 따라서 현재 증거상 BEND 문제는 단순 CS polarity 문제가 아니다.

가능성이 높은 원인:

- BEND CS 물리 배선이 `gpio3_22`가 아님
- BEND CS pad는 토글되지만 보드/레벨시프터/드라이버 CSN까지 도달하지 않음
- BEND 드라이버의 MISO 또는 전원/enable 상태 문제
- BEND 드라이버 자체 불량 또는 미장착

### 9.3 FEED는 SPI가 아니라 STEP/PWM 쪽 문제로 보임

`motor_diag.py FEED 1000 2.0` 결과:

```text
STANDSTILL pre-PWM: rx=0x00F80 SG_VAL=3 STST flags=[OK]
RUN @ 1000 Hz:      rx=0x00F80 SG_VAL=3 STST flags=[OK]
```

판단:

FEED 칩은 SPI 설정을 받지만, PWM 구간에서도 `STST`가 계속 1이고 SG 값도 변하지 않는다. 즉 FEED 칩 입장에서는 STEP edge를 보지 못하고 있다.

추가로 `current.dts`를 확인했더니 PWM4 STEP pad가 다음처럼 low-drive 값으로 내려가 있었다.

```dts
pwm4grp {
    fsl,pins = <0x12c 0x38c 0x00 0x02 0x00 0x106>;
};
```

문서상 `0x106`은 low drive / 신호 약함으로 기록되어 있고, 이전 working case는 `0x1c6`이었다.

조치:

- `current.dts`에서 PWM4 STEP pad config를 `0x106`에서 `0x1c6`으로 복구

```dts
pwm4grp {
    fsl,pins = <0x12c 0x38c 0x00 0x02 0x00 0x1c6>;
};
```

### 9.4 현재 분리된 문제

현재는 문제가 두 갈래로 분리됐다.

| 축 | SPI config | STEP 인식 | 현재 판단 |
|----|------------|-----------|-----------|
| FEED | 정상 | 비정상 | STEP/PWM/pad drive/배선 문제 |
| BEND | 비정상 | 미판단 | CS 배선/CS pad/드라이버 응답 문제 |
| LIFT | 정상 | 미검증 | SPI는 정상, STEP 공통이면 FEED와 같은 STEP 문제 가능 |

### 9.5 다음 권장 순서

1. `current.dts` 변경분을 DTB로 컴파일하여 보드에 적용 후 reboot
2. reboot 후 `dmesg`에서 `cs1 >= max 1`, `micfil`, `pinctrl` 에러가 사라졌는지 확인
3. FEED에 대해 `motor_diag.py FEED 1000 2.0` 재실행
4. FEED에서 `STST`가 RUN으로 바뀌면 STEP pad drive 문제가 맞음
5. BEND는 별도로 CS 물리 라인을 scope/logic analyzer로 확인

현재 로컬 `current.dts`에는 다음 조치를 반영했다.

- `micfil@30ca0000`: disabled
- PWM4 `pwm4grp`: `0x106` -> `0x1c6`
- `spidev@1`, `spidev@2`: disabled
