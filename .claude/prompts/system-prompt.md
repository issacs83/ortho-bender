# System Prompt

You are working on the ortho-bender project: a dental orthodontic wire bending
machine built on the NXP i.MX8MP SoC.

## Project Context
This is an FDA Class II medical device that bends orthodontic wires to match
patient-specific treatment plans. The system uses:
- Cortex-A53 quad-core running Linux (Yocto) for application-level software
- Cortex-M7 running FreeRTOS for real-time motor control and safety
- NPU (2.3 TOPS) for ML-based springback prediction and wire inspection
- 3-6 axis motion system (Feed, Rotate, Bend minimum; potentially 6-axis)

## Key Files
- `src/shared/ipc_protocol.h` -- Canonical IPC protocol between A53 and M7
- `src/shared/bcode_types.h` -- B-code data types (L, beta, theta)
- `src/firmware/source/motion/motion_controller.c` -- Core motion state machine
- `src/app/cam/cam_engine.cpp` -- CAM algorithm orchestrator
- `src/app/cam/springback/springback_model.cpp` -- Springback compensation
- `kas/base.yml` -- Yocto build manifest
- `meta-ortho-bender/conf/machine/ortho-bender-imx8mp.conf` -- Machine def

## Conventions
- Korean communication, English code/comments
- IEC 62304 traceability: every change linked to requirement ID
- Safety-critical M7 code: MISRA C, no dynamic alloc, ISR minimal work
- B-code coordinate system: L (mm), beta (degrees), theta (degrees)
- Wire materials: always specify material type for any springback calculation

## Domain Terminology
- B-code: Machine instructions (Feed L, Rotate beta, Bend theta)
- Springback: Elastic recovery of wire after bending; must overbend to compensate
- NiTi: Nickel-titanium shape-memory alloy; needs heating above Af temperature
- Af: Austenite finish temperature (the temperature above which NiTi is superelastic)
- Treatment plan: Orthodontist's prescribed wire shape for a patient
- Archwire: The wire that runs through brackets on teeth
