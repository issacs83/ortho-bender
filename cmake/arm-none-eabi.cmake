##
# @file arm-none-eabi.cmake
# @brief CMake toolchain file for ARM Cortex-M7 cross-compilation
# @note Used with: cmake -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake
#
# Targets: i.MX8MP M7 core (ARMv7E-M, FPv5-D16 FPU)
##

set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

# Compiler
set(CMAKE_C_COMPILER   arm-none-eabi-gcc)
set(CMAKE_CXX_COMPILER arm-none-eabi-g++)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)

# Binutils
set(CMAKE_OBJCOPY arm-none-eabi-objcopy)
set(CMAKE_OBJDUMP arm-none-eabi-objdump)
set(CMAKE_SIZE    arm-none-eabi-size)
set(CMAKE_AR      arm-none-eabi-ar)
set(CMAKE_RANLIB  arm-none-eabi-ranlib)

# Prevent CMake from testing the compiler with a full executable
# (bare-metal has no OS runtime to link against)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# Search paths: never search host paths for programs/libraries
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
