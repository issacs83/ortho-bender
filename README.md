# Ortho-Bender: Dental Orthodontic Wire Bending Machine

NXP i.MX8MP 기반 치과 교정 와이어 벤딩머신

## Overview

3D 치료 계획에서 생성된 와이어 형상을 B-code(Feed L, Rotate beta, Bend theta)로
변환하고, 다축 모터를 정밀 제어하여 환자 맞춤형 교정 와이어를 자동 생산합니다.

## Architecture

- **Cortex-A53 x4 (Linux/Yocto)**: Qt6 GUI, CAM 엔진, 환자 DB, NPU 추론, 비전
- **Cortex-M7 (FreeRTOS)**: 모션 제어, PID, 센서 취득, 안전 시스템
- **NPU 2.3 TOPS**: 스프링백 예측 ML, 와이어 결함 감지
- **Dual ISP**: 와이어 품질 검사 카메라

## Quick Start

```bash
# M7 firmware build
cmake -B build-firmware -S src/firmware -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake
cmake --build build-firmware

# A53 app (host test build)
cmake -B build-app -S src/app
cmake --build build-app

# Full Yocto image
KAS_BUILD_DIR=build-ortho-bender kas shell kas/base.yml:kas/ortho-bender-dev.yml
```

## Project Structure

```
src/app/          - A53 Linux applications
src/firmware/     - M7 FreeRTOS firmware
src/shared/       - Shared A53/M7 headers
meta-ortho-bender/ - Custom Yocto layer
kas/              - KAS build manifests
tests/            - Unit/integration/system tests
docs/             - Design documentation
```

## Regulatory

- FDA Class II 510(k)
- IEC 62304 Software Safety Class B
- ISO 13485 / ISO 14971

## License

Proprietary - All rights reserved
