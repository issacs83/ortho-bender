# J21 EXP_CN 최종 핀맵 확정 및 dtsi 재매핑 지시서

| 항목 | 값 |
|------|----|
| 문서 ID | `docs/hardware/j21-pin-assignment.md` |
| 리비전 | v1.0 (Phase 6 Option A 승인 반영) |
| 작성자 | circuit-engineer |
| 작성일 | 2026-04-13 |
| 상태 | Task #13 / #14 입력 확정 |
| 상위 문서 | `docs/hardware/adapter-board-spec.md` §18 |
| 기반 근거 | SPF-46370 Rev.B1 p.4 (SAI Usage), p.18 (EXP_CN J21 + NTB0104/NTS0104 레벨시프터) |
| 대상 dtsi | `meta-ortho-bender/recipes-bsp/linux/linux-imx/dts/imx8mp-ortho-bender-motors.dtsi` |
| 승인 옵션 | Option A — 쪽보드 진행 + dtsi 전면 재매핑 + TCA9555 I2C expander |

---

## 1. 배경 및 목적

이전 사양서 `adapter-board-spec.md` 초안에서 두 가지 HW Open Issue가 식별되었다.

| ID | 이슈 | 상태 |
|----|------|------|
| HW-OI-1 | 모터제어 신호 11개 vs J21 직결 가능 GPIO 8개 → **3개 부족** | 본 문서에서 **RESOLVED** |
| HW-OI-3 | 현재 `imx8mp-ortho-bender-motors.dtsi`가 사용하는 **SAI1_RX\*, SAI3_RX\*** 패드가 EVK J21/J22 어디에도 노출되지 않음 (물리적 불가) | 본 문서에서 **RESOLVED** |

사용자가 승인한 **Option A** 는 다음 세 축을 동시에 적용한다.

1. 쪽보드(Adapter Board) 제작을 그대로 진행
2. dtsi를 **EVK J21에 실제로 라우트되는 패드 그룹**(SAI5 + ECSPI2 + I2C3 + PWM)으로 **전면 재매핑**
3. HOME 스위치 4채널은 실시간 요건이 없으므로 **TCA9555 I2C GPIO expander**로 분리 (STEP/DIR/CS/DRV_ENN/ESTOP 은 직결 고정)

본 문서는 이 세 축을 수행하기 위한 **핀 단위 확정 테이블**, **기능→핀 할당**, **TCA9555 할당**, **dtsi 재매핑 지시서**, **배선 여유 검증**을 제공한다. Task #13 (dtsi 수정), Task #14 (GPIO→PAD 매핑 업데이트), Task #15 (MEMORY 업데이트) 담당자는 본 문서의 테이블을 **그대로 복사/참조**하여 작업할 수 있어야 한다.

---

## 2. J21 40-Pin 물리 핀맵 (확정)

### 2.1 테이블 컬럼 정의

- **Pin#**: J21 물리 핀 번호 (1~40, 2×20 헤더, Raspberry Pi Model B 호환 풋프린트)
- **J21 라벨**: SPF-46370 Rev.B1 p.18 스키매틱 네트명
- **EVK 내부 경로**:
  - `DIRECT` — i.MX8MP 패드에서 NTB0104/NTS0104 1개만 통과하여 J21까지 도달
  - `NTB0104 (U55/U57)` — auto-direction dual-supply 변환기 (1V8↔3V3), **C_load < 70 pF HARD LIMIT**
  - `NTS0104 (U56)` — 단방향 translator
  - `PCA6416A (U59)` — I2C GPIO 확장기 경유 → **실시간 critical path 사용 절대 금지**
- **i.MX8MP PAD**: Reference Manual Rev.3 IOMUXC 공식 PAD 명
- **SoC GPIO**: GPIO bank/line (LINUX_GPIO 번호)
- **쪽보드 용도**: Ortho-Bender 모터제어 기능 할당
- **RT**: 실시간 가능 (Y = STEP/DIR 가능, N = HOME/진단용만)

### 2.2 J21 40-Pin 완전 핀맵

| Pin# | J21 라벨 | EVK 경로 | i.MX8MP PAD | SoC GPIO | 쪽보드 용도 | RT |
|-----:|----------|----------|-------------|----------|------------|:--:|
|  1 | VEXP_3V3 | DIRECT (PMIC) | — | — | 로직 전원 입력 | — |
|  2 | VEXP_5V | DIRECT (VDD_5V) | — | — | 미사용 (TVS만) | — |
|  3 | I2C3_SDA_3V3 | NTB0104 (U55) | `I2C3_SDA` | I2C3 bus | **TCA9555 + EEPROM** | — |
|  4 | VEXP_5V | DIRECT | — | — | 미사용 | — |
|  5 | I2C3_SCL_3V3 | NTB0104 (U55) | `I2C3_SCL` | I2C3 bus | **TCA9555 + EEPROM** | — |
|  6 | GND | — | — | — | GND_LOGIC | — |
|  7 | UART3_RTS_3V3 | NTS0104 (U56) | `SAI5_RXD0` (ALT1 UART3_RTS_B) | GPIO3_IO21 | **금지** (EVK LED 겸용) | N |
|  8 | UART3_TXD_3V3 | NTS0104 (U56) | `ECSPI1_SCLK` (ALT1 UART3_RX) | GPIO5_IO06 | (옵션) M7 debug UART TX | N |
|  9 | GND | — | — | — | GND_LOGIC | — |
| 10 | UART3_RXD_3V3 | NTS0104 (U56) | `ECSPI1_MOSI` (ALT1 UART3_TX) | GPIO5_IO07 | (옵션) M7 debug UART RX | N |
| 11 | EXP_P1_1 | PCA6416A | — (U59 P0_0) | via i2c-3 0x20 | **금지** (실시간 불가) | N |
| 12 | PWM4_3V3 | NTB0104 (U58) | `SAI5_RXD3` (ALT1 PWM4_OUT) | GPIO3_IO24 | **BEND STEP** (PWM4 or GPIO) | Y |
| 13 | EXP_P1_2 | PCA6416A | — (U59 P0_1) | via i2c-3 0x20 | **금지** | N |
| 14 | GND | — | — | — | GND_LOGIC | — |
| 15 | EXP_P1_3 | PCA6416A | — (U59 P0_2) | via i2c-3 0x20 | **금지** | N |
| 16 | EXP_P1_4 | PCA6416A | — (U59 P0_3) | via i2c-3 0x20 | **금지** | N |
| 17 | VEXP_3V3 | DIRECT | — | — | 로직 전원 (1번과 병렬) | — |
| 18 | EXP_P1_5 | PCA6416A | — (U59 P0_4) | via i2c-3 0x20 | **금지** | N |
| 19 | ECSPI2_MOSI_3V3 | NTB0104 (U57) | `ECSPI2_MOSI` | ECSPI2 bus | **SPI MOSI** (daisy-chain 입력) | Y |
| 20 | GND | — | — | — | GND_LOGIC | — |
| 21 | ECSPI2_MISO_3V3 | NTB0104 (U57) | `ECSPI2_MISO` | ECSPI2 bus | **SPI MISO** (daisy-chain 출력) | Y |
| 22 | EXP_P1_6 | PCA6416A | — (U59 P0_5) | via i2c-3 0x20 | **금지** | N |
| 23 | ECSPI2_SCLK_3V3 | NTB0104 (U57) | `ECSPI2_SCLK` | ECSPI2 bus | **SPI SCLK** | Y |
| 24 | ECSPI2_SS0_3V3 | NTB0104 (U57) | `ECSPI2_SS0` | ECSPI2 SS0 | **SPI CS (chain 공통)** | Y |
| 25 | GND | — | — | — | GND_LOGIC | — |
| 26 | EXP_P1_7 | PCA6416A | — (U59 P0_6) | via i2c-3 0x20 | **금지** | N |
| 27 | I2C_ID_SDA | DIRECT | `HDMI_DDC_SDA` | HDMI I2C | 미사용 (RPi HAT ID EEPROM) | — |
| 28 | I2C_ID_SCL | DIRECT | `HDMI_DDC_SCL` | HDMI I2C | 미사용 | — |
| 29 | SAI5_RXD0 / GPIO3_IO21 | NTB0104 (U58) | `SAI5_RXD0` | GPIO3_IO21 | **금지** (EVK on-board LED D14) | N |
| 30 | GND | — | — | — | GND_LOGIC | — |
| 31 | SAI5_RXD1 / GPIO3_IO22 | NTB0104 (U58) | `SAI5_RXD1` | GPIO3_IO22 | **FEED STEP** (M7 GPT OC) | Y |
| 32 | PWM4_3V3 (dup) | NTB0104 (U58) | `SAI5_RXD3` (동일 네트 pin12 duplicate) | GPIO3_IO24 | 미사용 (pin12와 동일 네트) | — |
| 33 | SAI5_RXD2 / GPIO3_IO23 | NTB0104 (U58) | `SAI5_RXD2` | GPIO3_IO23 | **금지** (EVK on-board LED D15) | N |
| 34 | GND | — | — | — | GND_LOGIC | — |
| 35 | SAI5_RXC / GPIO3_IO20 | NTB0104 (U58) | `SAI5_RXC` | GPIO3_IO20 | **LIFT CS3** (soft CS, Phase 2) | N (low-rate) |
| 36 | SAI5_RXD3 / GPIO3_IO24 | NTB0104 (U58) | `SAI5_RXD3` | GPIO3_IO24 | **FEED DIR** (정적 출력) | Y |
| 37 | SAI5_RXFS / GPIO3_IO19 | NTB0104 (U58) | `SAI5_RXFS` | GPIO3_IO19 | **ROTATE CS2** (soft CS, Phase 2) | N (low-rate) |
| 38 | SAI5_RXD1 (dup) | NTB0104 (U58) | `SAI5_RXD1` (pin31 duplicate) | GPIO3_IO22 | 미사용 (pin31과 동일 네트) | — |
| 39 | GND | — | — | — | GND_LOGIC | — |
| 40 | SAI5_RXC (dup) | NTB0104 (U58) | `SAI5_RXC` (pin35 duplicate) | GPIO3_IO20 | 미사용 (pin35과 동일 네트) | — |

### 2.3 EVK 내부 경로 분류 요약

| 카테고리 | 핀 수 | J21 핀 번호 |
|----------|:---:|-------------|
| 전원 (VEXP_3V3/5V) | 4 | 1, 2, 4, 17 |
| GND | 8 | 6, 9, 14, 20, 25, 30, 34, 39 |
| ECSPI2 (NTB0104 U57, RT OK) | 4 | 19, 21, 23, 24 |
| SAI5 GPIO3 (NTB0104 U58, RT OK) | 6 (5 unique) | 31, 32, 35, 36, 37, 38 |
| SAI5 EVK LED shared (금지) | 2 | 29, 33 |
| PWM4 (NTB0104 U58, RT OK) | 2 (duplicate pin) | 12, 32 (=pin12 dup) |
| UART3 (NTS0104 U56) | 3 | 7, 8, 10 |
| I2C3 (NTB0104 U55, RT N/A) | 2 | 3, 5 |
| HDMI ID EEPROM I2C | 2 | 27, 28 |
| **PCA6416A (실시간 금지)** | 7 | 11, 13, 15, 16, 18, 22, 26 |

**핵심**: J21에서 실시간 모터제어에 사용 가능한 직결 GPIO는 **ECSPI2 4핀 + SAI5 (RXFS/RXC/RXD1/RXD3) 4핀 + PWM4 1핀 = 총 9핀**이다 (EVK LED 공유 RXD0/RXD2 제외). 여기에 I2C3 2핀 + UART3 3핀이 옵션 자원으로 추가된다.

---

## 3. 모터제어 기능 → J21 핀 최종 할당

### 3.1 신호 요구 인벤토리

| # | 기능 | 신호 수 | 실시간 | 방향 | 비고 |
|:-:|------|:---:|:---:|:---:|------|
| 1 | ECSPI2 SCLK | 1 | Y | OUT | daisy-chain 공통 |
| 2 | ECSPI2 MOSI | 1 | Y | OUT | daisy-chain 입력 |
| 3 | ECSPI2 MISO | 1 | Y | IN | daisy-chain 반환 |
| 4 | ECSPI2 SS (CS 공통) | 1 | Y | OUT | HW SS0 또는 GPIO soft-CS |
| 5 | FEED STEP | 1 | Y | OUT | GPT3 OC, 25 kHz |
| 6 | BEND STEP | 1 | Y | OUT | GPT4 OC 또는 PWM4, 25 kHz |
| 7 | FEED DIR | 1 | Y | OUT | 정적 (μs 지연 허용) |
| 8 | BEND DIR | 1 | Y | OUT | 정적 |
| 9 | DRV_ENN 공통 | 1 | Y | OUT | E-STOP HW 경로 상류 |
| 10 | ESTOP_IN 버튼 피드백 | 1 | Y | IN (edge IRQ) | M7 ISR < 1 ms |
| 11 | SPI_INT (선택) | 1 | N | IN | 사용하지 않음 — 대안: M7 폴링 |
| 12 | I2C3 SDA/SCL | 2 | N | IO | TCA9555 + EEPROM |
| 13 | HOME ×4 (FEED/BEND/ROTATE/LIFT) | 4 | N | IN | TCA9555 경유 |
| 14 | (Phase 2) ROTATE CS | 1 | N (low) | OUT | soft CS |
| 15 | (Phase 2) LIFT CS | 1 | N (low) | OUT | soft CS |
| 16 | (Phase 2) ROTATE STEP/DIR | 2 | Y | OUT | **J21 직결 불가 → HW-OI-1.1** |
| 17 | (Phase 2) LIFT STEP/DIR | 2 | Y | OUT | **J21 직결 불가 → HW-OI-1.1** |

**필수 Phase 1 실시간 신호 = 10개** (SPI 4 + STEP×2 + DIR×2 + DRV_ENN + ESTOP).
J21 직결 실시간 가능 핀 = **9개**. 여기서 ECSPI2 HW SS0가 CS 공통 역할을 겸임하므로 **10개 = 9 개 직결 + 공유 1개**로 수렴한다.

### 3.2 Phase 1 신호 → J21 핀 할당 (확정)

| 기능 | J21 Pin | i.MX8MP PAD | 할당 GPIO | 새 pinctrl 그룹 | 근거 |
|------|:------:|-------------|-----------|-----------------|------|
| ECSPI2 SCLK | **23** | `ECSPI2_SCLK` | ECSPI2_SCLK (ALT0) | `pinctrl_motor_spi` | NTB0104 U57 — HW 페리 |
| ECSPI2 MOSI | **19** | `ECSPI2_MOSI` | ECSPI2_MOSI (ALT0) | `pinctrl_motor_spi` | 동일 |
| ECSPI2 MISO | **21** | `ECSPI2_MISO` | ECSPI2_MISO (ALT0) | `pinctrl_motor_spi` | 동일 |
| ECSPI2 SS0 (CS chain 공통) | **24** | `ECSPI2_SS0` | ECSPI2_SS0 (ALT0) → Linux driver가 cs-gpios로 재사용 | `pinctrl_motor_spi` | HW SS0, `cs-gpios = <&gpio5 13 GPIO_ACTIVE_LOW>` 로 soft-CS 전환 |
| FEED STEP | **31** | `SAI5_RXD1` | GPIO3_IO22 (ALT5) | `pinctrl_motor_stepdir` | M7 GPT3 OC |
| FEED DIR | **36** | `SAI5_RXD3` | GPIO3_IO24 (ALT5) | `pinctrl_motor_stepdir` | 정적 출력 |
| BEND STEP | **12** | `SAI5_RXD3` (PWM4_OUT ALT1) **대안 A** OR `SAI5_MCLK` PAD는 J21 미노출 → **채택: PWM4_OUT pin12** | PWM4 (ALT1) 또는 GPIO3_IO24 (ALT5) | `pinctrl_motor_stepdir` | **주의**: pin12 = pin32 (dup)이고, 이 네트는 내부적으로 pin36 SAI5_RXD3와 **동일 SoC 패드** → **충돌** |
| BEND DIR | **(재지정)** | `ECSPI1_MOSI` (pin10 UART3_RX ALT1) → ALT5 GPIO5_IO07 | GPIO5_IO07 (ALT5) | `pinctrl_motor_stepdir` | UART3 debug 포기 |
| DRV_ENN 공통 | **(재지정)** | `ECSPI1_SCLK` (pin8 UART3_TX) → ALT5 GPIO5_IO06 | GPIO5_IO06 (ALT5) | `pinctrl_motor_estop` | active-LOW enable |
| ESTOP_IN | **35** | `SAI5_RXC` | GPIO3_IO20 (ALT5) | `pinctrl_motor_estop` | 인터럽트 가능 |
| (Phase 2) ROTATE CS | **37** | `SAI5_RXFS` | GPIO3_IO19 (ALT5) | `pinctrl_motor_spi` | soft CS |
| (Phase 2) LIFT CS | **재할당 필요 (pin35 ESTOP와 충돌)** | TCA9555 P1_5 (low-rate OK) | 확장기 | `pinctrl_motor_i2c_exp` | 초당 수 회 CS 토글, I2C 지연 수용 |

### 3.3 BEND STEP / pin12 vs pin36 PAD 충돌 해결

SPF-46370 스키매틱 분석 결과:

- pin 12 = pin 32 = `PWM4_3V3` **네트** (U58 NTB0104 채널 1)
- pin 36 = `SAI5_RXD3_3V3` **네트** (U58 NTB0104 채널 4)

두 네트는 서로 **다른 NTB0104 채널**이지만 i.MX8MP 내부에서는 `SAI5_RXD3` 패드 하나가 ALT1 (PWM4_OUT) 또는 ALT5 (GPIO3_IO24) 중 하나로만 동작한다. 즉 **pin12와 pin36은 같은 SoC 패드를 공유**한다.

→ **결론**:
- **pin36을 GPIO3_IO24 = FEED DIR로 사용** (정적)
- **pin12를 동일 패드의 PWM4_OUT 으로 사용할 수 없음** (MUX 배타)
- **BEND STEP은 대체 패드가 필요**

### 3.4 BEND STEP 대체 — GPIO5 블록 재활용

UART3 debug를 포기하고 다음 두 패드를 GPIO5로 재매핑한다:

| 목적 | J21 Pin | PAD | ALT / GPIO |
|------|:-------:|-----|------------|
| BEND STEP | **pin 8** (UART3_TXD_3V3) | `ECSPI1_SCLK` | ALT5 → **GPIO5_IO06** |
| BEND DIR | **pin 10** (UART3_RXD_3V3) | `ECSPI1_MOSI` | ALT5 → **GPIO5_IO07** |
| DRV_ENN | **pin 7** (UART3_RTS_3V3) | `ECSPI1_MISO` | ALT5 → **GPIO5_IO08** |
| ESTOP_IN | **pin 35** | `SAI5_RXC` | ALT5 → **GPIO3_IO20** |

> **ECSPI1 패드 확인**: SPF-46370 p.4/p.18 UART3 구성을 확인하면 J21 pin7/8/10은 ECSPI1 풋프린트 패드(`ECSPI1_MISO/SCLK/MOSI`)에 UART3 alt (ALT1)로 라우팅된다. 이들은 GPIO5_IO06-08 (ALT5)로 각각 재설정 가능하다. UART3 디버그 기능을 포기하면 즉시 사용 가능.

> **BSP 검증 선결**: Task #13 수행 전 bsp-engineer가 `imx8mp.dtsi` 및 `imx8mp-pinfunc.h`에서 `MX8MP_IOMUXC_ECSPI1_SCLK__GPIO5_IO06` 매크로 존재를 확인해야 한다. 표준 NXP BSP에는 존재함 (확인 대상 파일: `arch/arm64/boot/dts/freescale/imx8mp-pinfunc.h`).

### 3.5 CS3 (LIFT soft-CS) pin35 충돌 해결

원안에서 pin35(`SAI5_RXC`=GPIO3_IO20)를 LIFT CS3로 사용했으나, 본 재매핑에서는 **pin35가 ESTOP_IN**으로 더 중요하다 (실시간 IRQ 요건). LIFT CS3는 Phase 2 자원이고 CS 토글 주파수가 ≤ 100 Hz 수준이므로 **TCA9555 P1_5 (low-rate OK)**로 이동해도 문제 없다.

- **ROTATE CS2** = pin37 = GPIO3_IO19 **(유지)**
- **LIFT CS3** = TCA9555 P1_5 **(변경)**

> **타이밍 검증**: TCA9555 I2C 400 kHz, 1-byte write ≈ 60 μs. CS3 토글 주파수 ≤ 100 Hz → 기간 10 ms. 10 ms / 60 μs = 166× 여유. 단, Phase 2 ROTATE/LIFT는 교대 구동(look-ahead §4.1) 전제 하에 허용.

### 3.6 Phase 2 ROTATE/LIFT STEP/DIR — HW-OI-1.1 신규 이슈

J21 직결 가능 실시간 GPIO가 Phase 1 10개로 **모두 소진**되었다. Phase 2의 ROTATE/LIFT STEP×2 + DIR×2 = 4개는 **J21로 커버 불가**하다. 두 가지 경로를 제안한다.

| 옵션 | 설명 | 장단점 |
|------|------|--------|
| (A) TMC5160 내부 sequencer | TMC5160의 온칩 motion controller (ramp generator) 사용, SPI로 목표위치만 전달 | STEP/DIR 신호 자체가 불필요. 아키텍처 §4 TMC260C 외부 STEP 모델과 분리되지만 TMC5160만의 장점 활용. **권장** |
| (B) Phase 2에서 EVK → 최종 커스텀 SoM 이관 | 최종 제품 보드에서는 SAI1/SAI3 패드가 사용 가능 → 현재 dtsi의 GPIO4_IO00-31 매핑 복원 | 최종 BOM 단계까지 Phase 2 테스트 불가 |

**현재 결정**: Phase 1 쪽보드 브링업까지는 **(A) TMC5160 내부 sequencer 사용**으로 진행. 즉 Phase 2 ROTATE/LIFT는 ECSPI2 SPI + CS (CS2 직결 / CS3 확장기) 만으로 제어되고, STEP/DIR 물리 선은 쪽보드에서 **M7 GPIO 대신 TMC5160 SPI 명령**으로 대체된다. 이는 `motor-control-architecture.md` §4.3의 "외부 STEP 모델"을 Phase 2에만 부분 완화하는 것이며, **결재 대상 변경사항**이다. 결재 승인 전까지는 Phase 2 테스트 블로킹 상태로 간주한다 → **HW-OI-1.1 으로 신규 등록**.

### 3.7 최종 Phase 1 실시간 핀 테이블

| # | 기능 | J21 Pin | SoC PAD | GPIO | Direction | 레벨 | 주석 |
|:-:|------|:------:|---------|------|-----------|------|------|
| 1 | SPI SCLK | 23 | `ECSPI2_SCLK` | ECSPI2 HW | OUT | 3V3 | 2 MHz 통일 |
| 2 | SPI MOSI | 19 | `ECSPI2_MOSI` | ECSPI2 HW | OUT | 3V3 | daisy-chain 입력 |
| 3 | SPI MISO | 21 | `ECSPI2_MISO` | ECSPI2 HW | IN | 3V3 | daisy-chain 반환 |
| 4 | SPI CS chain | 24 | `ECSPI2_SS0` | ECSPI2 HW (cs-gpios로 soft-CS 모드) | OUT | 3V3 | 공통 CS |
| 5 | FEED STEP | 31 | `SAI5_RXD1` | GPIO3_IO22 | OUT | 3V3 | GPT3 OC |
| 6 | FEED DIR | 36 | `SAI5_RXD3` | GPIO3_IO24 | OUT | 3V3 | 정적 |
| 7 | BEND STEP | 8 | `ECSPI1_SCLK` | GPIO5_IO06 | OUT | 3V3 | GPT4 OC; UART3 debug 포기 |
| 8 | BEND DIR | 10 | `ECSPI1_MOSI` | GPIO5_IO07 | OUT | 3V3 | 정적 |
| 9 | DRV_ENN 공통 | 7 | `ECSPI1_MISO` | GPIO5_IO08 | OUT (active-LOW) | 3V3 | 초기값 HIGH=disable |
| 10 | ESTOP_IN | 35 | `SAI5_RXC` | GPIO3_IO20 | IN (falling edge IRQ) | 3V3 | PU+HYS 필수 |
| 11 | ROTATE CS2 (P2) | 37 | `SAI5_RXFS` | GPIO3_IO19 | OUT | 3V3 | soft-CS |
| — | LIFT CS3 (P2) | TCA9555 | P1_5 | — | OUT | 3V3 | low-rate |
| — | I2C3 SDA | 3 | `I2C3_SDA` | I2C3 HW | IO | 3V3 | TCA9555 + EEPROM |
| — | I2C3 SCL | 5 | `I2C3_SCL` | I2C3 HW | OUT | 3V3 | 동일 |

Phase 1 자원 집계: **ECSPI2 (4) + SAI5 GPIO3 (3: IO19/IO20/IO22/IO24 중 4개) + GPIO5 (3: IO06/IO07/IO08) + I2C3 (2) = 12 J21 핀** 사용. 실시간 10 + I2C 2. HW-OI-1 해결.

---

## 4. TCA9555 I2C GPIO Expander 할당

### 4.1 하드웨어 배치

| 항목 | 값 |
|------|----|
| 부품 | TCA9555PWR (TSSOP-24) |
| 주소 | `0x20` (A0=A1=A2=GND) |
| 버스 | I2C3 (J21 pin3/5), 400 kHz Fast-mode |
| Vcc | V_DRV_VIO_3V3 (쪽보드 내부 3.3V 재생성) |
| INT 출력 | **미사용** — polling only (10 ms period, 홈잉 중에만 활성) |
| 디바운스 | 입력 측 RC: 10 kΩ series + 100 nF shunt = τ 1 ms |
| 풀업 | 내부 풀업 없음 → 외부 10 kΩ to Vcc (스위치 open 시 HIGH) |

### 4.2 16-bit 포트 할당

| Port.Bit | 방향 | 신호 | 타입 | 연결 | 비고 |
|----------|:----:|------|------|------|------|
| P0.0 | IN | HOME_FEED | NC switch | J_LIM_F | 홈잉 시 polling |
| P0.1 | IN | HOME_BEND | NC switch | J_LIM_B | 홈잉 시 polling |
| P0.2 | IN | HOME_ROTATE | NC switch | J_LIM_R | Phase 2 |
| P0.3 | IN | HOME_LIFT | NC switch | J_LIM_L | Phase 2 |
| P0.4 | IN | AUX_IN_0 | 예비 입력 | TP_AUX0 | overtravel / custom sensor |
| P0.5 | IN | AUX_IN_1 | 예비 입력 | TP_AUX1 | |
| P0.6 | IN | DOOR_INTLK | 안전 커버 스위치 | J_DOOR | ISO 13849 interlock (옵션) |
| P0.7 | IN | CABINET_TEMP_ALARM | NTC 아날로그비교기 OC | U_TEMP | over-temp warn |
| P1.0 | OUT | STATUS_LED_PWR | LED green | D_LED1 | 전원 OK |
| P1.1 | OUT | STATUS_LED_RUN | LED blue | D_LED2 | 모터 동작 중 |
| P1.2 | OUT | STATUS_LED_FAULT | LED red | D_LED3 | SG2/OVTEMP/ESTOP 래치 |
| P1.3 | OUT | STATUS_LED_HOME | LED white | D_LED4 | 홈 완료 |
| P1.4 | OUT | BUZZER_EN | PWM buzzer enable | Q_BUZ | 알람 |
| P1.5 | OUT | LIFT_CS3 | TMC5160 soft-CS | U4 TMC5160 | low-rate (Phase 2) |
| P1.6 | OUT | SPARE_OUT_0 | 예비 | TP_SP0 | — |
| P1.7 | OUT | SPARE_OUT_1 | 예비 | TP_SP1 | — |

### 4.3 타이밍 가정

- I2C 400 kHz × 1 byte (TCA9555 input register read) ≈ 60 μs (SLA+W+CMD + SR + SLA+R + 2byte + NACK)
- HOME polling 주기 = 10 ms (M7 homing task) → dutycycle 60/10000 = 0.6 %
- LIFT CS3 write 60 μs per edge × 2 edges per SPI frame = 120 μs per chain transfer → SPI 2 MHz 80 μs frame 대비 CS wrap 200 μs total. Phase 2 < 100 Hz frame rate 에서 수용.
- **HARD RULE**: TCA9555 라인은 E-STOP 경로 **불가** — DRV_ENN은 직결 GPIO5_IO08 (pin7) 고정.

---

## 5. dtsi 재매핑 지시서 (Task #13 복사/붙여넣기용)

### 5.1 현재 dtsi에서 **삭제**할 항목 (라인 번호: `imx8mp-ortho-bender-motors.dtsi` 기준)

#### 5.1.1 삭제할 pinctrl group 전체

- **`pinctrl_m7_motor_gpio: m7-motorgpiogrp`** (라인 349~409) — SAI1_RX* 엔트리 9개 전부 삭제
- **`pinctrl_m7_motor2_gpio: m7-motor2gpiogrp`** (라인 429~491) — SAI5_RXFS/RXC/RXD1/RXD3/MCLK + SAI3_RXFS/RXC/RXD/TXFS 엔트리 9개 전부 삭제

#### 5.1.2 삭제할 iomux entry 상세

```
(삭제 A) — SAI1 pad group 전체 (EVK J21 미노출)
  MX8MP_IOMUXC_SAI1_RXFS__GPIO4_IO00   0x00000146
  MX8MP_IOMUXC_SAI1_RXC__GPIO4_IO01    0x00000146
  MX8MP_IOMUXC_SAI1_RXD0__GPIO4_IO02   0x00000146
  MX8MP_IOMUXC_SAI1_RXD1__GPIO4_IO03   0x00000146
  MX8MP_IOMUXC_SAI1_RXD2__GPIO4_IO04   0x00000146
  MX8MP_IOMUXC_SAI1_RXD3__GPIO4_IO05   0x000001C6
  MX8MP_IOMUXC_SAI1_RXD4__GPIO4_IO06   0x000001C6
  MX8MP_IOMUXC_SAI1_RXD5__GPIO4_IO07   0x000001D6
  MX8MP_IOMUXC_SAI1_RXD6__GPIO4_IO08   0x000001C6

(삭제 B) — SAI3 pad group 전체 (EVK J21 미노출)
  MX8MP_IOMUXC_SAI3_RXFS__GPIO4_IO28   0x00000146
  MX8MP_IOMUXC_SAI3_RXC__GPIO4_IO29    0x000001C6
  MX8MP_IOMUXC_SAI3_RXD__GPIO4_IO30    0x000001C6
  MX8MP_IOMUXC_SAI3_TXFS__GPIO4_IO31   0x000001D6

(삭제 C) — SAI5_MCLK 단일 엔트리 (J21 미노출)
  MX8MP_IOMUXC_SAI5_MCLK__GPIO3_IO25   0x00000146
```

#### 5.1.3 삭제할 gpio-hog 노드

- `&gpio4 { step0-hog, dir0-hog, step1-hog, dir1-hog, drv-enn-hog, diag0-hog, diag1-hog, estop-hog, home-bend-hog }` (라인 134~217) — **전체 삭제**
- `&gpio3 { cs2-hog, cs3-hog, step2-hog, dir2-hog, step3-hog }` (라인 225~265) — **전체 삭제**
- `&gpio4 { dir3-hog, diag2-hog, diag3-hog, home-rotate-hog }` (라인 267~309) — **전체 삭제**

> 모든 hog는 새 핀맵으로 재작성되므로 기존 노드를 모두 걷어낸 뒤 섹션 5.2의 신규 hog를 추가한다.

### 5.2 **추가**할 pinctrl group (전체 신규 작성)

```dts
&iomuxc {
	/*
	 * pinctrl_motor_spi — ECSPI2 daisy-chain (M7 exclusive)
	 *
	 * J21 pin 19 (MOSI) / 21 (MISO) / 23 (SCLK) / 24 (SS0)
	 * NTB0104 U57 translation, C_load < 70 pF per line.
	 *
	 * CS0 is the shared chain CS for all 4 TMC drivers.
	 * ROTATE CS2 (J21 pin 37, GPIO3_IO19) is a soft GPIO CS driven
	 * by the M7; it lives in pinctrl_motor_stepdir because it shares
	 * the same SAI5 pad group as the STEP/DIR signals.  LIFT CS3 is
	 * on TCA9555 P1.5 and does not appear here.
	 *
	 * Pad config: 0x00000146 = DSE6, FSEL1, no pull — SPI high-speed
	 *             0x00000106 = DSE6, FSEL0, no pull — CS slower edges
	 */
	pinctrl_motor_spi: motorspigrp {
		fsl,pins = <
			MX8MP_IOMUXC_ECSPI2_SCLK__ECSPI2_SCLK		0x00000146
			MX8MP_IOMUXC_ECSPI2_MOSI__ECSPI2_MOSI		0x00000146
			MX8MP_IOMUXC_ECSPI2_MISO__ECSPI2_MISO		0x00000146
			MX8MP_IOMUXC_ECSPI2_SS0__GPIO5_IO13		0x00000106
			/*
			 * SS0 muxed as GPIO5_IO13 so the ECSPI2 driver can use
			 * it as a cs-gpios entry.  This keeps the CS glitch-free
			 * during daisy-chain framing (HW SS0 pulses between bytes
			 * which corrupts 160-bit chain frames — AN-002 warning).
			 */
		>;
	};

	/*
	 * pinctrl_motor_stepdir — STEP/DIR + soft-CS group
	 *
	 * FEED STEP : J21 pin 31, SAI5_RXD1 -> GPIO3_IO22 (M7 GPT3 OC)
	 * FEED DIR  : J21 pin 36, SAI5_RXD3 -> GPIO3_IO24 (static)
	 * BEND STEP : J21 pin 8,  ECSPI1_SCLK -> GPIO5_IO06 (M7 GPT4 OC)
	 *             NOTE: repurposes EVK UART3_TXD pad; UART3 debug must
	 *             be reassigned or dropped before enabling this pin.
	 * BEND DIR  : J21 pin 10, ECSPI1_MOSI -> GPIO5_IO07 (static)
	 * ROTATE CS2: J21 pin 37, SAI5_RXFS  -> GPIO3_IO19 (soft CS)
	 *
	 * NTB0104 U57/U58 both rated for 20 MHz, pad FSEL1 recommended.
	 */
	pinctrl_motor_stepdir: motorstepdirgrp {
		fsl,pins = <
			MX8MP_IOMUXC_SAI5_RXD1__GPIO3_IO22		0x00000146
			MX8MP_IOMUXC_SAI5_RXD3__GPIO3_IO24		0x00000146
			MX8MP_IOMUXC_SAI5_RXFS__GPIO3_IO19		0x00000146
			MX8MP_IOMUXC_ECSPI1_SCLK__GPIO5_IO06		0x00000146
			MX8MP_IOMUXC_ECSPI1_MOSI__GPIO5_IO07		0x00000146
		>;
	};

	/*
	 * pinctrl_motor_estop — safety signals
	 *
	 * DRV_ENN   : J21 pin 7,  ECSPI1_MISO -> GPIO5_IO08 (active-LOW)
	 *             Initial value HIGH (drivers disabled); M7 releases
	 *             after SPI bring-up + self test.
	 * ESTOP_IN  : J21 pin 35, SAI5_RXC   -> GPIO3_IO20 (pull-up + HYS,
	 *             falling-edge IRQ, M7 must assert DRV_ENN within 1 ms).
	 *
	 * Pad config: 0x000001D6 = DSE6, PUE+PUS+HYS — input w/ hysteresis
	 *             0x00000146 = DSE6, FSEL1       — DRV_ENN output
	 */
	pinctrl_motor_estop: motorestopgrp {
		fsl,pins = <
			MX8MP_IOMUXC_ECSPI1_MISO__GPIO5_IO08		0x00000146
			MX8MP_IOMUXC_SAI5_RXC__GPIO3_IO20		0x000001D6
		>;
	};

	/*
	 * pinctrl_motor_i2c_exp — I2C3 bus for TCA9555 + 24FC256 EEPROM
	 *
	 * SDA: J21 pin 3  (I2C3_SDA)
	 * SCL: J21 pin 5  (I2C3_SCL)
	 * 400 kHz fast-mode; 4.7k external pull-up on adapter board.
	 *
	 * Pad config: 0x400001C2 per NXP recommended I2C
	 *             (SION=1, DSE3, ODE=1, PUE+PUS, no HYS).
	 */
	pinctrl_motor_i2c_exp: motori2cexpgrp {
		fsl,pins = <
			MX8MP_IOMUXC_I2C3_SCL__I2C3_SCL			0x400001C2
			MX8MP_IOMUXC_I2C3_SDA__I2C3_SDA			0x400001C2
		>;
	};
};
```

### 5.3 **수정**할 상위 노드 바인딩

#### 5.3.1 `&ecspi2` — cs-gpios + daisy-chain

```dts
&ecspi2 {
	#address-cells = <1>;
	#size-cells = <0>;
	pinctrl-names = "default";
	pinctrl-0 = <&pinctrl_motor_spi &pinctrl_motor_stepdir
		     &pinctrl_motor_estop>;

	/*
	 * Soft-CS via GPIO5_IO13 (was ECSPI2_SS0).  Daisy-chain frames
	 * require continuous CS-low across 160 bits; HW SS0 would toggle
	 * between 8-bit words and corrupt the chain.
	 */
	cs-gpios = <&gpio5 13 GPIO_ACTIVE_LOW>;

	/*
	 * M7 exclusive — Linux keeps the iomux and the node disabled so the
	 * controller stays claimed by the AIPS-1 partition owned by the M7.
	 */
	status = "disabled";

	tmc260_feed: motor@0 {
		compatible = "trinamic,tmc260";
		reg = <0>;
		spi-max-frequency = <2000000>;
		spi-cpol;
		spi-cpha;
		status = "disabled";
	};

	tmc260_bend: motor@1 {
		compatible = "trinamic,tmc260";
		reg = <0>;	/* chain position 1; reg=0 because soft-CS is shared */
		spi-max-frequency = <2000000>;
		spi-cpol;
		spi-cpha;
		status = "disabled";
	};

	/*
	 * Phase 2 TMC5160 drivers on the same chain.  They use the internal
	 * ramp generator (motion-control-architecture §4 Phase 2 update)
	 * so no STEP/DIR signals are routed off-board for them.  CS2 is a
	 * soft GPIO (GPIO3_IO19); CS3 lives on TCA9555 P1.5 (see i2c3 node).
	 */
	tmc5160_rotate: motor@2 {
		compatible = "trinamic,tmc5160";
		reg = <0>;
		spi-max-frequency = <4000000>;
		spi-cpol;
		spi-cpha;
		status = "disabled";
	};

	tmc5160_lift: motor@3 {
		compatible = "trinamic,tmc5160";
		reg = <0>;
		spi-max-frequency = <4000000>;
		spi-cpol;
		spi-cpha;
		status = "disabled";
	};
};
```

> **참고**: 4개 모두 soft-CS가 공통 1개로 chain되므로 `reg = <0>` 로 통일되고 실제 드라이버 선택은 chain frame 내 position으로 구분된다. 이는 linux spi_device 모델과 어긋나므로 실제 트리에서는 **단일 `motor@0` 노드 + compatible string "trinamic,tmc-chain"** 형태로 단일화하거나, M7 독점이므로 Linux 측 binding을 완전히 생략해도 된다. Task #13 구현자가 커널 SPI core 충돌을 피하려면 `status = "disabled"` 로 유지하고 stub 노드는 단일 `motor_chain@0` 하나로 축약할 것을 권장.

#### 5.3.2 `&gpio3`, `&gpio5` gpio-hog 재작성

```dts
&gpio3 {
	/* FEED STEP — GPT3 OC (J21 pin 31, SAI5_RXD1) */
	feed-step-hog {
		gpio-hog;
		gpios = <22 GPIO_ACTIVE_HIGH>;
		output-low;
		line-name = "FEED-STEP-M7";
	};

	/* FEED DIR (J21 pin 36, SAI5_RXD3) */
	feed-dir-hog {
		gpio-hog;
		gpios = <24 GPIO_ACTIVE_HIGH>;
		output-low;
		line-name = "FEED-DIR-M7";
	};

	/* ROTATE CS2 — TMC5160 soft CS (J21 pin 37, SAI5_RXFS) */
	rotate-cs2-hog {
		gpio-hog;
		gpios = <19 GPIO_ACTIVE_LOW>;
		output-high;
		line-name = "ROTATE-CS2-M7";
	};

	/* ESTOP_IN — falling-edge IRQ input (J21 pin 35, SAI5_RXC) */
	estop-in-hog {
		gpio-hog;
		gpios = <20 GPIO_ACTIVE_LOW>;
		input;
		line-name = "ESTOP-IN-M7";
	};
};

&gpio5 {
	/* BEND STEP — GPT4 OC (J21 pin 8, ECSPI1_SCLK) */
	bend-step-hog {
		gpio-hog;
		gpios = <6 GPIO_ACTIVE_HIGH>;
		output-low;
		line-name = "BEND-STEP-M7";
	};

	/* BEND DIR (J21 pin 10, ECSPI1_MOSI) */
	bend-dir-hog {
		gpio-hog;
		gpios = <7 GPIO_ACTIVE_HIGH>;
		output-low;
		line-name = "BEND-DIR-M7";
	};

	/* DRV_ENN — shared driver enable (J21 pin 7, ECSPI1_MISO) */
	drv-enn-hog {
		gpio-hog;
		gpios = <8 GPIO_ACTIVE_LOW>;
		output-high;	/* disabled = safe default */
		line-name = "TMC-DRV-ENN-M7";
	};

	/* SPI soft CS (J21 pin 24, ECSPI2_SS0 remuxed to GPIO5_IO13) */
	spi-cs-chain-hog {
		gpio-hog;
		gpios = <13 GPIO_ACTIVE_LOW>;
		output-high;
		line-name = "SPI-CS-CHAIN-M7";
	};
};
```

#### 5.3.3 `&i2c3` — TCA9555 + EEPROM

```dts
&i2c3 {
	clock-frequency = <400000>;
	pinctrl-names = "default";
	pinctrl-0 = <&pinctrl_motor_i2c_exp>;
	status = "okay";

	/* Adapter board IO expander — HOME switches + LEDs + LIFT CS3 */
	tca9555_motor: gpio@20 {
		compatible = "ti,tca9555";
		reg = <0x20>;
		gpio-controller;
		#gpio-cells = <2>;
		/*
		 * Port0 = inputs (HOME x4 + AUX x2 + DOOR + TEMP)
		 * Port1 = outputs (LEDs x4 + BUZ + LIFT_CS3 + spare x2)
		 * The M7 owns this expander through rpmsg-i2c proxy; Linux
		 * exposes it only for homing diagnostics at boot.
		 */
		status = "okay";
	};

	adapter_eeprom: eeprom@50 {
		compatible = "atmel,24c256";
		reg = <0x50>;
		pagesize = <64>;
		status = "okay";
	};
};
```

### 5.4 삭제/추가 변경 요약표

| 구분 | 항목 | 개수 |
|------|------|------|
| 삭제 | SAI1_RX* iomux entries | 9 |
| 삭제 | SAI3_RX*/TXFS iomux entries | 4 |
| 삭제 | SAI5_MCLK iomux entry | 1 |
| 삭제 | gpio4 hog entries | 13 |
| 삭제 | gpio3 hog entries | 5 |
| 추가 | pinctrl_motor_spi group | 1 (4 pins) |
| 추가 | pinctrl_motor_stepdir group | 1 (5 pins) |
| 추가 | pinctrl_motor_estop group | 1 (2 pins) |
| 추가 | pinctrl_motor_i2c_exp group | 1 (2 pins) |
| 추가 | gpio3 hog entries | 4 |
| 추가 | gpio5 hog entries | 4 |
| 추가 | i2c3 TCA9555 + 24FC256 nodes | 2 |
| 수정 | ecspi2 node (cs-gpios, compatible) | 1 |

---

## 6. 배선 여유 검증 (Signal Integrity)

### 6.1 NTB0104 / NTS0104 Capacitive Load 재계산

EVK 보드 측 U55 ~ U58 NTB0104GU12 및 U56 NTS0104는 데이터시트 §8.3 (NXP NTB0104 SCES727) 기준 **Cload ≤ 70 pF** HARD LIMIT 이다. 새 핀맵 배선 모델:

**가정**:
- J21 헤더 암 소켓 pin ↔ 쪽보드 관통홀: 2 mm stub, 0.5 pF
- 2-layer FR4, 6 mil 트레이스, 트레이스 1 cm 당 **1 pF**
- 쪽보드 J21 수신 입구의 ESD TVS (TPD4E05U06) 단자 **3 pF/ch**
- 시리즈 저항 22 Ω (0603) 후 ISO7741 입력 **4 pF/ch**
- ISO7741 후 TMC 드라이버 입력 **6 pF/ch** (별도 격리 도메인, EVK 측 Cload 와 무관)

**라인별 합산 (EVK NTB0104 부터 ISO7741 입력까지, 격리 이전 구간)**:

| 라인 | 트레이스 길이 | 트레이스 C | J21 소켓 | TVS | ISO Cin | 합계 | 여유 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| ECSPI2 SCLK (pin23) | 3 cm | 3 pF | 0.5 | 3 | 4 | **10.5 pF** | 6.7× |
| ECSPI2 MOSI (pin19) | 3 cm | 3 | 0.5 | 3 | 4 | 10.5 | 6.7× |
| ECSPI2 MISO (pin21) | 3 cm | 3 | 0.5 | 3 | 4 | 10.5 | 6.7× |
| ECSPI2 SS0→GPIO5_IO13 (pin24) | 3 cm | 3 | 0.5 | 3 | 4 | 10.5 | 6.7× |
| FEED STEP (pin31) | 4 cm | 4 | 0.5 | 3 | 4 | 11.5 | 6.1× |
| FEED DIR (pin36) | 4 cm | 4 | 0.5 | 3 | 4 | 11.5 | 6.1× |
| BEND STEP (pin8) | 4 cm | 4 | 0.5 | 3 | 4 | 11.5 | 6.1× |
| BEND DIR (pin10) | 4 cm | 4 | 0.5 | 3 | 4 | 11.5 | 6.1× |
| DRV_ENN (pin7) | 5 cm | 5 | 0.5 | 3 | 4 | 12.5 | 5.6× |
| ESTOP_IN (pin35) | 5 cm | 5 | 0.5 | 3 | 4 | 12.5 | 5.6× |
| ROTATE CS2 (pin37) | 5 cm | 5 | 0.5 | 3 | 4 | 12.5 | 5.6× |
| I2C3 SDA/SCL (pin3/5) | 3 cm | 3 | 0.5 | 3 | — (직결 TCA9555 Cin ~10 pF) | 16.5 | 4.2× |

**결론**: 모든 라인에서 70 pF HARD LIMIT 대비 **최소 4.2×, 평균 6× 여유**. 쪽보드 내 트레이스 최대 **5 cm** 제약과 TVS 1개 + 22 Ω 시리즈 1개 구성으로 NTB0104 drive 능력 내.

> **Phase 7 레이아웃 HARD RULE**:
> - 모든 J21 → ISO7741 입력 트레이스 **≤ 5 cm**
> - TVS는 J21 헤더 관통홀로부터 **≤ 5 mm**
> - 22 Ω 시리즈 저항은 TVS 이후, ISO7741 입력 직전
> - 쪽보드 진입 후 stub 금지 (T-junction 금지)

### 6.2 STEP 라인 Rise/Fall Time 시뮬레이션 가정

TMC260C datasheet §7.4 Table 7.5: `t_SH`, `t_SL` min 1 μs (STEP high/low minimum width). 25 kHz 스텝 주파수 → 40 μs period, duty 50% → 20 μs high / 20 μs low. 에지 왜곡 예산:

| 단계 | 지연 / 왜곡 |
|------|-----|
| M7 GPT OC → i.MX 패드 | 2 ns (internal) |
| 패드 → J21 네트 (NTB0104 U58) prop delay | 3.4 ns typ |
| J21 → 쪽보드 트레이스 (4 cm @ 0.15 c) | 0.2 ns |
| TVS + 22 Ω series RC (C_tot 11.5 pF × 22 Ω = 0.25 ns τ) | 0.5 ns 10-90% |
| ISO7741 prop delay typ | 11 ns |
| ISO7741 pulse width distortion | 2 ns |
| 2차측 → TMC260C STEP input | 1 ns |
| **총 지연 (edge-to-edge)** | **≈ 18 ns** |
| **총 pulse width distortion** | **≤ 3 ns** |

25 kHz (40 μs period)에서 왜곡 3 ns는 **0.0075 %** → TMC 요구 1 μs min pulse 대비 **330× 여유**.

**축간 skew**: FEED STEP (GPIO3_IO22)과 BEND STEP (GPIO5_IO06)은 **서로 다른 NTB0104 칩**(U58 vs 내부 UART3 경로)을 통과한다. NTB0104 칩간 prop delay 편차 = ±2 ns (데이터시트). 추가로 트레이스 길이 편차 ±1 cm = ±0.05 ns. 총 축간 skew **≤ 3 ns** — 아키텍처 §4.3 목표 < 50 ns 대비 **16× 여유**.

> **Phase 1 테스트 시**: FEED/BEND STEP을 스코프 2채널로 동시 측정하여 skew 측정 값 < 10 ns 확인. 실패 시 pcb 레이아웃 길이 매칭 재수행.

### 6.3 ECSPI1 패드를 GPIO로 재사용하는 것에 대한 위험 분석

| 위험 | 평가 | 완화 |
|------|------|------|
| EVK U-Boot / kernel이 ECSPI1 을 다른 용도로 클레임 | LOW — `imx8mp-evk.dts` ECSPI1은 J22 헤더에만 노출, J21 ECSPI1 패드는 UART3 alt로 바운드 | Task #13에서 `&ecspi1 { status = "disabled"; }` 명시 |
| UART3 debug 경로 상실로 초기 부팅 실패 시 디버그 불가 | MED | UART1 콘솔 유지 (EVK 기본) + SWD (J_DEBUG pin) 백업 |
| GPIO5_IO06~08 sysfs 충돌 (RPi HAT 관습상 GPIO14-15 = UART) | LOW — Linux gpio-hog로 예약 | hog가 gpio subsys에서 선점 |
| M7 에서 GPIO5 접근 latency | 동일 AIPS bus, TCM 접근 < 3 cycle | 검증 대상 — M7 브링업 테스트 |

---

## 7. Open Issue 업데이트

### 7.1 RESOLVED

| ID | 요약 | 해결 방법 |
|----|------|----------|
| **HW-OI-1** | J21 가용 GPIO 부족 (11 필요 vs 8) | **RESOLVED** — 본 문서 §3. ECSPI1 패드 3개 재활용(UART3 debug 포기) + TCA9555로 HOME×4 및 LIFT CS3 이관하여 실시간 10 + I2C 2 = 12 J21 핀에 정착 |
| **HW-OI-3** | 현재 dtsi의 SAI1/SAI3 패드가 EVK J21 미노출 | **RESOLVED** — 본 문서 §5 dtsi 재매핑 지시서 전체. 삭제 27개 iomux/hog, 추가 14개 iomux + 8개 hog + 2개 i2c 노드 |

### 7.2 NEW (본 작업에서 파생)

| ID | 설명 | 담당 | 결정 시점 |
|----|------|------|----------|
| **HW-OI-1.1** | Phase 2 ROTATE/LIFT STEP/DIR 4 핀을 J21 직결 불가 → TMC5160 내부 sequencer 사용으로 아키텍처 §4.3 부분 변경 필요 | circuit-engineer + motion-control-engineer | Phase 2 설계 킥오프 전 결재 |
| **HW-OI-3.1** | `MX8MP_IOMUXC_ECSPI1_SCLK__GPIO5_IO06` 등 3개 매크로가 업스트림 `imx8mp-pinfunc.h`에 존재하는지 BSP 검증 | bsp-engineer | Task #13 착수 전 24h 이내 |
| **HW-OI-3.2** | i.MX8MP EVK U-Boot이 ECSPI1 패드를 부팅 과정에서 toggle하는지 확인 (DRV_ENN이 부팅 중 LOW로 pulse되면 모터 순간 여자 위험) | bsp-engineer | Task #13 구현 중 |
| **HW-OI-3.3** | I2C3 핀 3/5 에 EVK 기본 dts가 이미 바인딩한 장치 유무 확인 (EEPROM 주소 0x50 충돌 여부) | bsp-engineer | Task #13 구현 중 |

---

## 8. Task #13/#14/#15 체크리스트

### 8.1 Task #13 (dtsi 재매핑) — bsp-engineer

- [ ] `imx8mp-pinfunc.h`에서 `MX8MP_IOMUXC_ECSPI1_SCLK__GPIO5_IO06`, `ECSPI1_MOSI__GPIO5_IO07`, `ECSPI1_MISO__GPIO5_IO08`, `ECSPI2_SS0__GPIO5_IO13`, `I2C3_SCL__I2C3_SCL`, `I2C3_SDA__I2C3_SDA` 6개 매크로 존재 확인
- [ ] §5.1 삭제 대상 전부 제거
- [ ] §5.2 4개 pinctrl group 추가
- [ ] §5.3.1 ecspi2 노드 수정 (cs-gpios, disabled 유지)
- [ ] §5.3.2 gpio3/gpio5 hog 재작성
- [ ] §5.3.3 i2c3 노드에 TCA9555 + 24FC256 추가
- [ ] `&ecspi1 { status = "disabled"; };` 명시적 비활성화
- [ ] `&uart3 { status = "disabled"; };` 명시적 비활성화
- [ ] kas build 성공 + dtc warning 0 (cpp 에러 0)
- [ ] `make ARCH=arm64 dtbs` 후 `dtc -I dtb -O dts` 로 결과 dts에 GPIO3_IO19/20/22/24 + GPIO5_IO06/07/08/13 hog 라인 포함 확인
- [ ] USB 보호 주석 블록(라인 28~41) **유지** — 카메라 리소스 변경 없음

### 8.2 Task #14 (GPIO → PAD 매핑 문서 업데이트) — doc-manager

- [ ] `.claude/memory/project_m7_pin_map.md` 를 §3.7 테이블로 전면 교체
- [ ] Phase 1 HARD GATE 표 11개 신호 업데이트 (GPIO4 → GPIO3/GPIO5)
- [ ] USB 리소스 보호 HARD GATE 유지 (GPIO1_IO12/14 변경 없음)
- [ ] M7 HAL 코드 references 갱신 필요성 플래그 (firmware-engineer notify)

### 8.3 Task #15 (MEMORY 업데이트) — project-director

- [ ] MEMORY.md 에 `project_j21_pin_assignment.md` 엔트리 추가
- [ ] HW-OI-1/OI-3 RESOLVED 기록
- [ ] HW-OI-1.1/OI-3.1/OI-3.2/OI-3.3 NEW 기록
- [ ] adapter-board-spec.md §18 신규 섹션 링크

---

## 9. 참조 섹션 (adapter-board-spec.md §18 append 문안)

아래 블록을 `docs/hardware/adapter-board-spec.md` 의 §17과 §부록A 사이에 **§18** 로 삽입한다.

```markdown
---

## 18. J21 최종 핀맵 확정 (Option A 승인 반영)

사용자 승인(2026-04-13)에 따라 쪽보드를 Option A 로 진행하며, J21 핀맵 및
dtsi 재매핑 상세는 별도 문서 `docs/hardware/j21-pin-assignment.md` 에 확정되었다.

### 18.1 요약
- **HW-OI-1 / HW-OI-3**: 모두 RESOLVED — 해당 문서 §7 참조
- **실시간 Phase 1 모터 신호 10개**: ECSPI2 4 + SAI5 GPIO3 3 + GPIO5 3 (UART3 재활용)
- **TCA9555 I2C GPIO expander**: HOME ×4, STATUS LED ×4, LIFT CS3, AUX ×4, BUZZER
- **재매핑 신규 pinctrl**: `pinctrl_motor_spi`, `pinctrl_motor_stepdir`,
  `pinctrl_motor_estop`, `pinctrl_motor_i2c_exp`
- **삭제**: SAI1/SAI3/SAI5_MCLK 전체, GPIO4 hog 전부

### 18.2 파생 Open Issues
- **HW-OI-1.1**: Phase 2 ROTATE/LIFT STEP/DIR 를 TMC5160 internal sequencer 로
  대체 — motion-control-architecture §4.3 부분 변경 (결재 대상)
- **HW-OI-3.1..3**: BSP 검증 선결 항목 (pinfunc.h 매크로, U-Boot 토글, I2C3 충돌)

상세 핀 단위 테이블, dtsi 재매핑 diff, 배선 여유 계산은
`docs/hardware/j21-pin-assignment.md` 를 참조.
```

---

*End of document — j21-pin-assignment.md v1.0*
