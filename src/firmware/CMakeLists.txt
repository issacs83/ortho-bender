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
# MCUXpresso SDK paths (configure per environment)
# ──────────────────────────────────────────────

set(MCUX_SDK_DIR "" CACHE PATH "Path to MCUXpresso SDK for i.MX8MP")
set(FREERTOS_DIR "" CACHE PATH "Path to FreeRTOS kernel")

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
    ${CMAKE_CURRENT_SOURCE_DIR}/board
    ${CMAKE_CURRENT_SOURCE_DIR}/hal
    ${CMAKE_CURRENT_SOURCE_DIR}/source
    ${CMAKE_CURRENT_SOURCE_DIR}/source/drivers
    ${CMAKE_CURRENT_SOURCE_DIR}/../shared
)

# ──────────────────────────────────────────────
# Source files
# ──────────────────────────────────────────────

file(GLOB_RECURSE FIRMWARE_SOURCES
    "source/*.c"
    "board/*.c"
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

# Print size after build
add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_SIZE} ${PROJECT_NAME}
    COMMENT "Firmware size:"
)

# Generate .bin
add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary ${PROJECT_NAME} ${PROJECT_NAME}.bin
    COMMENT "Generating binary: ${PROJECT_NAME}.bin"
)
