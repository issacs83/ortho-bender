# Ortho-Bender Coding Rules

## C Standards (M7 Firmware)
- C11 for all M7 firmware code
- MISRA C:2012 guidelines for safety-critical modules (motion/, safety/)
- No dynamic memory allocation in ISR or after RTOS scheduler starts
- All variables initialized at declaration
- Bounds check all array/buffer accesses

## C++ Standards (A53 Application)
- C++17 for A53 application code
- RAII for resource management
- No raw pointers for ownership (use std::unique_ptr, std::shared_ptr)
- Exceptions disabled in embedded-facing code; use error codes

## Firmware Naming (M7)
- Functions: module_action_object (e.g., tmc5160_set_vmax, motion_execute_step)
- Macros: MODULE_DEFINE (e.g., MOTION_MAX_VELOCITY, TMC_SPI_CLOCK_HZ)
- Types: module_type_t (e.g., motion_state_t, tmc_status_t)
- Files: module_name.c/.h (e.g., tmc5160_driver.c, motion_controller.c)
- ISR handlers: MODULE_IRQHandler (e.g., TMC_DIAG_IRQHandler)

## Application Naming (A53)
- Classes: PascalCase (e.g., CamEngine, SpringbackModel)
- Methods/functions: snake_case (e.g., compute_bend_sequence)
- Constants: UPPER_SNAKE_CASE
- Files: snake_case.cpp/.h

## Architecture
- HAL abstraction for ALL peripheral access on M7
- No direct register access outside hal/ directory
- ISR handlers: set flag/post to queue, defer work to task
- State machines for all protocol and motion sequence implementations
- All IPC messages: serialize/deserialize through generated code from ipc_protocol.h

## Safety
- Watchdog timer for all production builds (200ms on M7)
- Stack overflow detection enabled in FreeRTOS
- Assert macros for debug builds, fault handler for production
- CRC32 for all stored configuration data
- TMC5160 DRV_STATUS: check on every poll cycle for overtemp/short/open-load

## Yocto Rules
- BBFILE_PRIORITY for meta-ortho-bender: 10 (highest)
- PACKAGE_CLASSES = "package_ipk"
- Recipe modifications: bbappend first, avoid direct edits
- Kernel patches: patches/ directory with series
- DTS includes: .dtsi extension, separate per subsystem
- Production builds: remove debug-tweaks, change root password

## Build
- M7: -Wall -Wextra -Werror -Os (production), -O0 -g (debug)
- A53: -Wall -Wextra -Wpedantic
- Static analysis: cppcheck for all C/C++, clang-tidy for A53 C++
- Code size: report Flash/RAM usage for M7 on every build

## Documentation (IEC 62304)
- Every source file MUST have a file-level comment: purpose, author, SW class
- Every public function MUST have doxygen-style documentation
- Change log maintained per-module for traceability
