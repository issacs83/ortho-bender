# Ortho-Bender Project Memory

## Project Overview
Dental orthodontic wire bending machine. Takes a 3D wire prescription (from
treatment planning software), converts it to B-code (Feed L, Rotate beta,
Bend theta sequences), and controls motors to produce the finished wire.

## Architecture
- SoC: NXP i.MX8MP (4x Cortex-A53 + 1x Cortex-M7 + NPU 2.3 TOPS)
- A53 (Linux): Qt6 GUI, CAM engine, patient DB, NPU inference, vision
- M7 (FreeRTOS): Motion control, PID, sensor acquisition, safety
- IPC: RPMsg (shared memory via rpmsg_lite / OpenAMP)
- NPU: Springback prediction ML, wire defect detection via eIQ/TFLite
- Camera: Dual ISP for wire inspection, calibrated machine vision

## Key Algorithms
- 3D curve -> B-code conversion (discretize curve into L/beta/theta moves)
- Springback compensation: material-dependent overbend calculation
  - NiTi: shape-memory behavior, temperature-dependent superelasticity
  - SS 304: standard elastic springback model
  - Beta-Ti: higher flexibility, lower springback than SS
  - CuNiTi: temperature-sensitive, similar to NiTi
- Trajectory planning: S-curve velocity profiles for smooth motion
- PID tuning: per-axis, per-load tuning parameters stored in config

## Build Environment
- Yocto/KAS: `KAS_BUILD_DIR=build-ortho-bender kas shell kas/base.yml:kas/ortho-bender-dev.yml`
- M7 firmware: `cmake -B build-firmware -S src/firmware -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake && cmake --build build-firmware`
- A53 app (native test): `cmake -B build-app -S src/app && cmake --build build-app`
- Unit tests: `cd tests && cmake -B build && cmake --build build && ctest`

## Current Status
- Phase: Project initialization
- Next: BSP bring-up on i.MX8MP EVK, then custom board design

## Key Decisions
- RPMsg over shared memory for A53-M7 IPC (vs. mailbox-only approach)
- FreeRTOS on M7 (vs. bare-metal) for task prioritization
- Qt6 for GUI (vs. web-based) for real-time responsiveness
- SQLite for patient DB (vs. PostgreSQL) for embedded simplicity
- ONNX Runtime / eIQ for NPU inference (vs. custom inference engine)
