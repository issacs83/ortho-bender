cmake_minimum_required(VERSION 3.20)

project(ortho-bender-app
    VERSION 0.1.0
    LANGUAGES C CXX
    DESCRIPTION "Ortho-Bender A53 Linux Application"
)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_compile_options(-Wall -Wextra -Wpedantic)

include(GNUInstallDirs)

# ──────────────────────────────────────────────
# Shared library (C sources from src/shared/)
# ──────────────────────────────────────────────

set(SHARED_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../shared)

add_library(ortho-bender-shared STATIC
    ${SHARED_DIR}/wire_materials.c
)

target_include_directories(ortho-bender-shared PUBLIC
    ${SHARED_DIR}
)

# ──────────────────────────────────────────────
# Submodules
# ──────────────────────────────────────────────

add_subdirectory(cam)
add_subdirectory(ipc)
# add_subdirectory(gui)       # Enable when Qt6 is available
# add_subdirectory(npu)       # Enable when eIQ SDK is available
# add_subdirectory(vision)    # Enable when camera HAL is available
# add_subdirectory(database)  # Enable when SQLite integration starts
