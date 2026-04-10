cmake_minimum_required(VERSION 3.20)

project(ortho-bender-firmware
    VERSION 0.1.0
    LANGUAGES C ASM
    DESCRIPTION "Ortho-Bender M7 FreeRTOS Firmware"
)

# ──────────────────────────────────────────────
# Toolchain (set via -DCMAKE_TOOLCHAIN_FILE)
# ──────────────────────────────────────────────

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# ──────────────────────────────────────────────
# MCUXpresso SDK paths
# ──────────────────────────────────────────────

set(SDK_DIR "/home/issacs/.openclaw/workspace/m7_sdk" CACHE PATH
    "Path to MCUXpresso SDK for i.MX8MP")
set(FREERTOS_DIR "${SDK_DIR}/rtos/freertos/freertos-kernel" CACHE PATH
    "Path to FreeRTOS kernel")
set(DEVICE_DIR "${SDK_DIR}/mcuxsdk/devices/MIMX8ML8" CACHE PATH
    "Path to MIMX8ML8 device files")
set(RPMSG_DIR "${SDK_DIR}/middleware/multicore/rpmsg_lite" CACHE PATH
    "Path to RPMsg-Lite library")
set(MU_DRIVER_DIR "${SDK_DIR}/mcuxsdk/drivers/mu" CACHE PATH
    "Path to MU (Messaging Unit) driver")
set(COMMON_DRIVER_DIR "${SDK_DIR}/mcuxsdk/drivers/common" CACHE PATH
    "Path to common SDK drivers (fsl_common)")

# ──────────────────────────────────────────────
# Compiler flags
# ──────────────────────────────────────────────

set(MCU_FLAGS
    -mcpu=cortex-m7
    -mthumb
    -mfpu=fpv5-d16
    -mfloat-abi=hard
)

add_compile_options(
    ${MCU_FLAGS}
    -Wall -Wextra -Werror
    -ffunction-sections
    -fdata-sections
    -fno-common
)

# CPU definition for MCUXpresso SDK device headers
add_compile_definitions(CPU_MIMX8ML8CVNKZ)

# Debug vs Release
if(CMAKE_BUILD_TYPE STREQUAL "Release")
    add_compile_options(-Os -DNDEBUG)
else()
    add_compile_options(-O0 -g3 -DDEBUG)
endif()

# ──────────────────────────────────────────────
# Include paths
# ──────────────────────────────────────────────

include_directories(
    # Project headers
    ${CMAKE_CURRENT_SOURCE_DIR}/board
    ${CMAKE_CURRENT_SOURCE_DIR}/hal
    ${CMAKE_CURRENT_SOURCE_DIR}/source
    ${CMAKE_CURRENT_SOURCE_DIR}/source/drivers
    ${CMAKE_CURRENT_SOURCE_DIR}/source/motion
    ${CMAKE_CURRENT_SOURCE_DIR}/source/safety
    ${CMAKE_CURRENT_SOURCE_DIR}/source/ipc
    ${CMAKE_CURRENT_SOURCE_DIR}/../shared

    # MCUXpresso SDK device headers
    ${DEVICE_DIR}
    ${DEVICE_DIR}/drivers

    # CMSIS Core headers (core_cm7.h etc.)
    ${SDK_DIR}/mcuxsdk/CMSIS/Core/Include

    # FreeRTOS headers
    ${FREERTOS_DIR}/include
    ${FREERTOS_DIR}/portable/GCC/ARM_CM7/r0p1

    # RPMsg-Lite headers
    ${RPMSG_DIR}/lib/include
    ${RPMSG_DIR}/lib/include/environment
    ${RPMSG_DIR}/lib/include/environment/freertos
    ${RPMSG_DIR}/lib/include/platform/imx8mp_m7

    # MU driver (required by rpmsg platform port)
    ${MU_DRIVER_DIR}

    # Common SDK drivers (fsl_common.h)
    ${COMMON_DRIVER_DIR}
)

# ──────────────────────────────────────────────
# Source files
# ──────────────────────────────────────────────

# Project firmware sources
file(GLOB_RECURSE FIRMWARE_SOURCES
    "source/*.c"
    "board/*.c"
)

# SDK, FreeRTOS, RPMsg-Lite, and MU driver sources compiled without -Werror
set(SDK_SOURCES
    ${DEVICE_DIR}/system_MIMX8ML8_cm7.c
    ${DEVICE_DIR}/gcc/startup_MIMX8ML8_cm7.S
    ${FREERTOS_DIR}/tasks.c
    ${FREERTOS_DIR}/queue.c
    ${FREERTOS_DIR}/list.c
    ${FREERTOS_DIR}/timers.c
    ${FREERTOS_DIR}/event_groups.c
    ${FREERTOS_DIR}/portable/GCC/ARM_CM7/r0p1/port.c
    ${FREERTOS_DIR}/portable/MemMang/heap_4.c

    # RPMsg-Lite core
    ${RPMSG_DIR}/lib/rpmsg_lite/rpmsg_lite.c
    ${RPMSG_DIR}/lib/rpmsg_lite/rpmsg_ns.c
    ${RPMSG_DIR}/lib/rpmsg_lite/rpmsg_queue.c
    ${RPMSG_DIR}/lib/common/llist.c
    ${RPMSG_DIR}/lib/virtio/virtqueue.c

    # RPMsg-Lite FreeRTOS environment port
    ${RPMSG_DIR}/lib/rpmsg_lite/porting/environment/rpmsg_env_freertos.c

    # RPMsg-Lite i.MX8MP M7 platform port (MU interrupt handling)
    ${RPMSG_DIR}/lib/rpmsg_lite/porting/platform/imx8mp_m7/rpmsg_platform.c

    # MU (Messaging Unit) driver for RPMsg doorbell interrupts
    ${MU_DRIVER_DIR}/fsl_mu.c

    # Common SDK driver (required by fsl_mu.c and others)
    ${COMMON_DRIVER_DIR}/fsl_common.c
    ${COMMON_DRIVER_DIR}/fsl_common_arm.c

    # Clock driver (required by fsl_mu.c CLOCK_EnableClock)
    ${DEVICE_DIR}/drivers/fsl_clock.c
)

# Build SDK/FreeRTOS as a static library with relaxed warnings
add_library(sdk_lib STATIC ${SDK_SOURCES})
target_compile_options(sdk_lib PRIVATE -Wno-error -Wno-unused-parameter -Wno-implicit-function-declaration)
target_include_directories(sdk_lib PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/source
    ${CMAKE_CURRENT_SOURCE_DIR}/source/ipc
    ${DEVICE_DIR}
    ${DEVICE_DIR}/drivers
    ${SDK_DIR}/mcuxsdk/CMSIS/Core/Include
    ${FREERTOS_DIR}/include
    ${FREERTOS_DIR}/portable/GCC/ARM_CM7/r0p1
    ${RPMSG_DIR}/lib/include
    ${RPMSG_DIR}/lib/include/environment
    ${RPMSG_DIR}/lib/include/environment/freertos
    ${RPMSG_DIR}/lib/include/platform/imx8mp_m7
    ${MU_DRIVER_DIR}
    ${COMMON_DRIVER_DIR}
)

# ──────────────────────────────────────────────
# Linker
# ──────────────────────────────────────────────

set(LINKER_SCRIPT ${CMAKE_CURRENT_SOURCE_DIR}/linker/MIMX8ML8xxxxx_cm7_ram.ld)

add_link_options(
    ${MCU_FLAGS}
    -T${LINKER_SCRIPT}
    -Wl,--gc-sections
    -Wl,-Map=${PROJECT_NAME}.map
    --specs=nano.specs
    --specs=nosys.specs
)

# ──────────────────────────────────────────────
# Target
# ──────────────────────────────────────────────

add_executable(${PROJECT_NAME}
    ${FIRMWARE_SOURCES}
)

target_link_libraries(${PROJECT_NAME} PRIVATE sdk_lib)

# Output as .elf for remoteproc loading
set_target_properties(${PROJECT_NAME} PROPERTIES
    OUTPUT_NAME "${PROJECT_NAME}"
    SUFFIX ".elf"
)

# Print size after build
add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_SIZE} ${PROJECT_NAME}.elf
    COMMENT "Firmware size:"
)

# Generate .bin
add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary ${PROJECT_NAME}.elf ${PROJECT_NAME}.bin
    COMMENT "Generating binary: ${PROJECT_NAME}.bin"
)
