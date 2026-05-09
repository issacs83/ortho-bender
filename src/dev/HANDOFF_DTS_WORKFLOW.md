# DTS 수정 → 컴파일 → 보드 적용 이관 문서

> Ortho-Bender 모터 벤치 (i.MX8MP EVK + Veyron 1×2A ×3) DTS 작업 표준 절차
>
> 작성: 2026-05-08

---

## 0. 작업 환경

### Host (개발 PC)
- 경로: `/home/issacs/work/quarkers/ortho-bender/src/dev/`
- 도구: `dtc`, `scp`, `ssh`, `sed` (apt 패키지 `device-tree-compiler`)

### Target (보드)
- IP: `192.168.77.2` (USB Ethernet, root 로그인)
- DTB 위치: `/run/media/boot-mmcblk2p1/imx8mp-ortho-bender-bench.dtb`
- 백업: `/run/media/boot-mmcblk2p1/imx8mp-ortho-bender-bench.dtb.bak`
- Serial: `/dev/ttyUSB2 @ 115200` (FT4232H)

### 핵심 fact
- DTS source는 보드에 직접 없음 → 현재 dtb를 디컴파일하여 작업
- `.bak`는 stock (PWM4 disabled, cs-gpios 3-CS 등 patch 안 된 상태)
- 작업 중 DTB는 `imx8mp-ortho-bender-bench.dtb`만 변경

---

## 1. 표준 작업 흐름

```
[보드] dtb pull   →   [host] dtc 디컴파일   →   [host] DTS 편집
                                                       ↓
[보드] reboot   ←   [host] dtb push   ←   [host] dtc 컴파일
   ↓
[보드] 검증 (dmesg, /dev/spidev*, /sys/class/pwm/)
```

---

## 2. 현재 dtb 가져오기

### 2.1 보드의 활성 dtb pull
```bash
cd /home/issacs/work/quarkers/ortho-bender/src/dev/

# 활성 dtb (현재 부팅에 사용 중)
scp -o StrictHostKeyChecking=no \
    root@192.168.77.2:/run/media/boot-mmcblk2p1/imx8mp-ortho-bender-bench.dtb \
    ./current.dtb

# stock 백업 (필요 시 복원 기준)
scp -o StrictHostKeyChecking=no \
    root@192.168.77.2:/run/media/boot-mmcblk2p1/imx8mp-ortho-bender-bench.dtb.bak \
    ./stock.dtb
```

### 2.2 dts로 디컴파일
```bash
dtc -I dtb -O dts current.dtb -o current.dts 2>/dev/null
dtc -I dtb -O dts stock.dtb   -o stock.dts   2>/dev/null
```

`-q` 옵션 또는 `2>/dev/null`로 경고 메시지 숨김. 디컴파일 결과 dts는 사람이 읽고 수정 가능.

---

## 3. DTS 편집 가이드

### 3.1 편집 방법
- 단순 변경: `sed -i 's|old|new|' file.dts`
- 복잡 변경: 텍스트 에디터 (vim, nano)
- 새 노드 추가: 디컴파일된 dts 구조 따라

### 3.2 핵심 노드 위치

| 노드 | 주소 | 용도 |
|------|------|------|
| `spi@30830000` | ECSPI2 | SPI bus (FEED/BEND/LIFT chip 통신) |
| `pwm@30690000` | PWM4 | STEP signal 8 kHz |
| `iomuxc@30330000` | IOMUXC | pad mux 설정 |

### 3.3 IOMUXC 핵심 그룹

`iomuxc/imx8mp-pinctrl/` 안:
- `motorbenchspigrp` (phandle 0x26): ECSPI2 SCLK/MOSI/MISO/SS0
- `motorbenchstepdirgrp` (phandle 0x27): BEND CS, DIR, ECSPI1 pads (LIFT CS 등)
- `motorbenchestopgrp` (phandle 0x28): E-STOP 관련
- `pwm4grp` (phandle 0x24): STEP pad alt2 PWM4

각 group의 `fsl,pins` 형식:
```
<mux_reg conf_reg input_reg mux_mode input_mux conf_value>
```
- `mux_reg`: pad의 mux register offset (IOMUXC base 기준)
- `conf_reg`: pad의 config register offset
- `input_reg`: input select register (대부분 0)
- `mux_mode`: alt mode (0~7)
- `input_mux`: input mux value (대부분 0)
- `conf_value`: pad config bits (DSE, SRE, PUE/PUS, HYS, ODE)

### 3.4 알려진 pad map

| 기능 | mux_reg | pad name | alt5 GPIO | board pin |
|------|---------|----------|-----------|-----------|
| FEED CS | 0x1FC | ECSPI2_SS0 | GPIO5_IO13 | J21 pin 24 (D6 via Veyron) |
| BEND CS | 0x138 | SAI5_RXD1 | GPIO3_IO22 | D7 |
| LIFT CS | 0x1E0 | ECSPI1_MOSI | GPIO5_IO07 | D8 (J21 pin 8) |
| STEP | 0x12C | SAI5_RXFS | GPIO3_IO21 | D5 (PWM4 alt2) |
| DIR | 0x140 | SAI5_RXD3 | GPIO3_IO23 | D4 |
| MOSI | 0x1F4 | ECSPI2_MOSI | - | J21 pin 19 |
| MISO | 0x1F8 | ECSPI2_MISO | - | J21 pin 21 |
| SCK | 0x1F0 | ECSPI2_SCLK | - | J21 pin 23 |

### 3.5 pad config 값 의미

`conf_value` 8-bit field (i.MX8MP IOMUXC SW_PAD_CTL):

| bit | name | 의미 |
|-----|------|------|
| 0 | SRE | Slew rate (0=slow, 1=fast) |
| 1-3 | DSE | Drive strength (000=disabled, 110=X6, 111=X7 max) |
| 4 | ODE | Open drain (0=push-pull) |
| 5 | HYS | Schmitt trigger (1=enabled) |
| 6 | PUS | Pull select (0=down, 1=up) |
| 7 | PUE | Pull/keeper enable (0=keeper, 1=pull) |
| 8 | PKE | Pull/keeper master enable |

검증된 값:
- `0x146` = DSE X4 + HYS off (default safe)
- `0x1c6` = DSE X6 + HYS off (cross-talk 감소)
- `0x1d6` = DSE X7 + HYS off (max drive, 시도해볼 값)
- `0x106` = DSE X1 (low drive, 신호 약함)

### 3.6 phandle 매핑

자주 쓰는 phandle:
- `0x29` = `gpio@30240000` (gpio5 = gpiochip4)
- `0x2a` = `gpio@30220000` (gpio3 = gpiochip2)
- `0x18` = `iomuxc` 자체

cs-gpios entry 형식: `<phandle line flags>`
- flags: 0=ACTIVE_HIGH, 1=ACTIVE_LOW

예: `<0x29 0x0d 0x01>` = gpio5_13 active-low

### 3.7 일반 변경 사례 (sed 패턴)

**cs-gpios 제거** (모든 CS를 manual GPIO toggle로):
```bash
sed -i '/cs-gpios = <0x29 0x0d 0x01>;/d' current.dts
```

**ECSPI2 num-cs 변경**:
```bash
sed -i 's|num-cs = <0x03>;|num-cs = <0x01>;|' current.dts
sed -i 's|fsl,spi-num-chipselects = <0x03>;|fsl,spi-num-chipselects = <0x01>;|' current.dts
```

**PWM4 활성화**:
```bash
awk '/pwm@30690000/{p=1} p && /status = "disabled";/ && !d {sub(/disabled/,"okay"); d=1} {print}' \
    current.dts > tmp && mv tmp current.dts
```

**pad config 변경 (예: DIR pad DSE X6 → X7)**:
```bash
# motorbenchstepdirgrp의 0x140 entry conf 값 1c6 → 1d6
sed -i 's|0x140 0x3a0 0x00 0x05 0x00 0x1c6|0x140 0x3a0 0x00 0x05 0x00 0x1d6|' current.dts
```

---

## 4. 컴파일

### 4.1 dts → dtb
```bash
dtc -I dts -O dtb -o new.dtb current.dts 2>&1 | grep -i error
```

에러 없이 완료되면 `new.dtb` 생성.

### 4.2 검증 (선택)
```bash
ls -la new.dtb       # 크기 확인 (보통 65KB 내외)
dtc -I dtb -O dts new.dtb -o /dev/null   # 다시 디컴파일 가능한지 검증
```

---

## 5. 보드에 push + reboot

### 5.1 dtb push
```bash
scp -o StrictHostKeyChecking=no new.dtb \
    root@192.168.77.2:/run/media/boot-mmcblk2p1/imx8mp-ortho-bender-bench.dtb
```

### 5.2 sync + reboot
```bash
ssh root@192.168.77.2 "sync; /sbin/reboot"
```

### 5.3 보드 재기동 대기
```bash
sleep 28
until timeout 4 ssh -o ConnectTimeout=3 root@192.168.77.2 "echo up" 2>/dev/null; do
    sleep 3
done
echo "BACK"
```

보드 reboot 약 25~30초.

---

## 6. 검증

### 6.1 SPI 정상 동작
```bash
ssh root@192.168.77.2 "ls /dev/spidev*"
```
- `1-CS DTS` (cs-gpios 1개): `/dev/spidev1.0`
- `3-CS DTS` (cs-gpios 3개): `/dev/spidev1.0 1.1 1.2`

### 6.2 PWM 활성화
```bash
ssh root@192.168.77.2 "ls /sys/class/pwm/"
# pwmchip0/1/2 → PWM4 active 시 pwmchip2
```

### 6.3 dmesg에서 에러 확인
```bash
ssh root@192.168.77.2 "dmesg | grep -iE 'spi_imx|pwm@|error|fail' | head -10"
```
- 정상 시: `spi_imx 30830000.spi: registered master spi1` 같은 메시지
- 실패 시:
  - `Error applying setting, reverse things back` → pinctrl 충돌
  - `cs1 >= max 1` → fsl,spi-num-chipselects 와 num-cs 불일치

### 6.4 pinctrl 적용 확인
```bash
ssh root@192.168.77.2 "cat /sys/kernel/debug/pinctrl/30330000.pinctrl/pinmux-pins | grep motorbench"
```
- 각 group의 pad가 정확히 claim 됐는지 확인

---

## 7. 일반적인 함정

### 7.1 pinctrl 충돌
같은 pad가 두 group에 들어가면 spi_imx가 reject:
```
spi_imx 30830000.spi: Error applying setting, reverse things back
```
→ 한 group에서 제거 (예: PWM4 노드가 0x12c owner면 motorbenchstepdirgrp에서 제거)

### 7.2 fsl,spi-num-chipselects vs num-cs 불일치
```
spi_imx: cs1 >= max 1
```
→ 둘 다 같은 값으로 set. cs-gpios entry 개수도 일치.

### 7.3 cs-gpios 제거 후 spidev 안 뜸
ECSPI2_SS0 pad가 alt5 GPIO mode인데 cs-gpios property 없으면 spi_imx가 HW SS 시도 → pad는 GPIO mode라 SS signal 안 나감.
→ 해결: pad mode를 alt0 (HW SS)로 변경 또는 cs-gpios 다시 추가.

### 7.4 Cross-talk
같은 SAI5 cluster pad끼리 PWM 신호 누설 (예: SAI5_RXFS PWM4 → SAI5_RXD3 DIR).
→ DTS pad config 강화 (DSE max + slow slew + pull-down) 또는 wire 측 다른 cluster pin으로 이동.

### 7.5 Reboot 후 PWM4 export 사라짐
PWM4는 부팅 시 자동 export 안 됨:
```bash
echo 0 > /sys/class/pwm/pwmchip2/export
```
모터 제어 script가 매번 export 실행해야.

---

## 8. 참고 — 검증된 working DTS 변경 사례

### Case A: 단축 BEND/FEED/LIFT manual CS 통일 (현재 setup)
- `cs-gpios` property 제거
- `num-cs = 1`, `fsl,spi-num-chipselects = 1` 유지
- Python에서 `SPI_NO_CS` ioctl + 모든 GPIO manual toggle
- 효과: 1층/2층/3층 코드 path 100% 동일

### Case B: PWM4 STEP 활성화 (검증 working)
- `pwm@30690000` status `disabled` → `okay`
- `pwm4grp` 추가 (`0x12c alt2 PWM4 conf 0x1c6`)
- `motorbenchstepdirgrp`에서 `0x12c` 제거 (PWM4가 owner)

### Case C: BEND CS 측 cross-talk 회피 (실패한 시도, 기록용)
- BEND wire pin 37 (SAI5_RXD1) → pin 26 (CE1) 시도 → CE1 NC, fail
- → pin 7 (UART2 console) 시도 → console claim 충돌, fail
- → 결국 pin 37 원위치 + D6/D7/D8 풀업 추가로 해결

---

## 9. 빠른 reference — 자주 쓰는 1-liner

```bash
# 작업 디렉토리
cd /home/issacs/work/quarkers/ortho-bender/src/dev/

# 1. 현재 dtb pull + decompile
scp root@192.168.77.2:/run/media/boot-mmcblk2p1/imx8mp-ortho-bender-bench.dtb ./current.dtb && \
    dtc -I dtb -O dts current.dtb -o current.dts 2>/dev/null

# 2. 편집 후 컴파일 + push + reboot
dtc -I dts -O dtb -o new.dtb current.dts 2>&1 | grep -i error && \
    scp new.dtb root@192.168.77.2:/run/media/boot-mmcblk2p1/imx8mp-ortho-bender-bench.dtb && \
    ssh root@192.168.77.2 "sync; /sbin/reboot"

# 3. reboot 대기 + 검증
sleep 28 && \
    until timeout 4 ssh -o ConnectTimeout=3 root@192.168.77.2 "echo up" 2>/dev/null; do sleep 3; done && \
    ssh root@192.168.77.2 "ls /dev/spidev*; ls /sys/class/pwm/; dmesg | grep spi_imx | tail -3"

# 4. stock 복원 (긴급)
scp ./stock.dtb root@192.168.77.2:/run/media/boot-mmcblk2p1/imx8mp-ortho-bender-bench.dtb && \
    ssh root@192.168.77.2 "sync; /sbin/reboot"
```

---

## 10. 트러블 시 회복

### 10.1 보드 SSH 접근 불가
- Serial 콘솔 (/dev/ttyUSB2 @ 115200)으로 접근
- u-boot에서 정지 후 stock dtb로 부팅 (수동 dtb 선택)

### 10.2 dtb 잘못 push로 부팅 실패
```bash
# 사용자가 SD card 빼서 host에서 직접 마운트
sudo mount /dev/sdX1 /mnt/boot
sudo cp ./stock.dtb /mnt/boot/imx8mp-ortho-bender-bench.dtb
sudo umount /mnt/boot
```
또는 EVK reset + recovery USB image 사용.

### 10.3 chip state stuck (reboot으로 회복 안 됨)
- PSU 12V 1분 OFF → ON (chip POR)
- chip 내부 thermal latch 또는 register state stuck 시 유일한 회복

---

## 11. 메모리 reference

- `~/.claude/projects/.../memory/motor_pwm_verified.md` — PWM4 working setup
- `~/.claude/projects/.../memory/motor_3axis_working_2026_05_08.md` — 3축 cycle 2 working setup
- `~/.claude/projects/.../memory/bench_spi_blocker.md` — 풀업 4.7k 필요 fact
- `~/.claude/projects/.../memory/j21-pin-assignment.md` — J21 핀맵 (있다면)
