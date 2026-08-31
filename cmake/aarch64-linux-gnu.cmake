##
# @file aarch64-linux-gnu.cmake
# @brief i.MX8MP A53(aarch64 리눅스) 크로스컴파일용 CMake 툴체인 파일
#
# 사용법:
#   cmake -S src/app -B build-app-arm --toolchain cmake/aarch64-linux-gnu.cmake
#
# Yocto SDK 를 쓰는 경우(권장 — 보드와 동일한 sysroot):
#   source /opt/fsl-imx-wayland/5.15-kirkstone/environment-setup-cortexa53-crypto-poky-linux
#   위 환경을 잡은 뒤 같은 명령을 실행하면 SDK 컴파일러/sysroot 를 자동으로 쓴다.
#
# SDK 가 없으면 우분투 크로스컴파일러(gcc-aarch64-linux-gnu)로 떨어진다.
# 이 경우 보드의 glibc 보다 호스트 쪽이 최신일 수 있으니, 실행 중
# GLIBC_2.xx not found 가 나오면 Yocto SDK 를 쓰거나 정적 링크할 것.
##

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

if(DEFINED ENV{OECORE_NATIVE_SYSROOT})
    # Yocto SDK 환경이 잡혀 있다.
    set(CMAKE_C_COMPILER   $ENV{CC})
    set(CMAKE_CXX_COMPILER $ENV{CXX})
    set(CMAKE_SYSROOT      $ENV{SDKTARGETSYSROOT})
    set(CMAKE_FIND_ROOT_PATH $ENV{SDKTARGETSYSROOT})
else()
    set(CMAKE_C_COMPILER   aarch64-linux-gnu-gcc)
    set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
endif()

# i.MX8MP 의 Cortex-A53 타깃 플래그
set(CMAKE_C_FLAGS_INIT   "-march=armv8-a+crc+crypto -mtune=cortex-a53")
set(CMAKE_CXX_FLAGS_INIT "-march=armv8-a+crc+crypto -mtune=cortex-a53")

# 탐색 경로: 호스트가 아니라 타깃 sysroot 만 뒤진다.
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
