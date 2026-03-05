# CMake toolchain file for cross-compiling to NXP i.MX8MP (Cortex-A53, aarch64)
#
# Usage:
#   cmake -B build-imx8mp -S . --toolchain cmake/aarch64-linux-gnu.cmake
#   cmake --build build-imx8mp
#
# With Yocto SDK (if installed):
#   source /opt/fsl-imx-xwayland/6.6-scarthgap/environment-setup-cortexa53-crypto-poky-linux
#   cmake -B build-imx8mp -S . --toolchain cmake/aarch64-linux-gnu.cmake

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

# Use Yocto SDK if available, otherwise fall back to Ubuntu cross-compiler
if(DEFINED ENV{OECORE_NATIVE_SYSROOT})
    # Yocto SDK environment sourced
    set(CMAKE_C_COMPILER   $ENV{CC})
    set(CMAKE_CXX_COMPILER $ENV{CXX})
    set(CMAKE_SYSROOT      $ENV{SDKTARGETSYSROOT})
    set(CMAKE_FIND_ROOT_PATH $ENV{SDKTARGETSYSROOT})
else()
    # Ubuntu cross-compiler (gcc-aarch64-linux-gnu)
    set(CMAKE_C_COMPILER   aarch64-linux-gnu-gcc)
    set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
endif()

# Target architecture flags for Cortex-A53 (i.MX8MP)
set(CMAKE_C_FLAGS_INIT   "-march=armv8-a+crc+crypto -mtune=cortex-a53")
set(CMAKE_CXX_FLAGS_INIT "-march=armv8-a+crc+crypto -mtune=cortex-a53")

# Search paths: only search target sysroot, not host
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
