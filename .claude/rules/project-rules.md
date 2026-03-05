# Project Rules — Ortho-Bender Wire Bending Machine

## Project: ortho-bender
## Description: Dental orthodontic wire bending machine using NXP i.MX8MP SoC

## Regulatory Classification
- FDA Class II Medical Device (510(k))
- IEC 62304 Software Safety Class B (potentially C for motion control)
- ISO 13485 Quality Management System
- ISO 14971 Risk Management

## Architecture Rules
1. All A53-M7 communication MUST use the shared IPC protocol in `src/shared/ipc_protocol.h`
2. M7 firmware MUST NOT use dynamic memory allocation (malloc/free) after init
3. All motion commands MUST pass through the safety limits check before execution
4. NPU inference runs on A53 side; results are sent to M7 via RPMsg
5. Emergency stop (E-STOP) MUST be handled in hardware interrupt on M7 with < 1ms latency

## Naming Conventions
- A53 C++ code: snake_case functions, PascalCase classes, UPPER_SNAKE_CASE constants
- M7 C code: module_action_object (e.g., stepper_set_speed), module_type_t for types
- B-code variables: L (feed length mm), beta (rotation degrees), theta (bend angle degrees)
- IPC messages: MSG_prefix (e.g., MSG_MOTION_CMD, MSG_STATUS_REPORT)

## Safety-Critical Code Rules
- All force/position/temperature readings MUST have range validation
- Watchdog timer: 200ms timeout on M7, pet in main loop
- Stack overflow detection: enabled for all FreeRTOS tasks
- All safety functions require dual-channel verification where possible
- MISRA C compliance for M7 safety-critical modules

## Wire Material Handling
- NiTi wire operations MUST include heating control (austenite finish temperature)
- Material properties lookup MUST use the shared material database
- Springback compensation MUST be applied per-material, per-wire-diameter

## Build Rules
- M7 firmware: arm-none-eabi-gcc, CMake, -Os -Wall -Wextra -Werror
- A53 application: aarch64-poky-linux-gcc (from Yocto SDK), CMake, Qt6
- Yocto: KAS manifests, meta-ortho-bender layer priority = 10
- Unit tests: build and run on host before cross-compile
