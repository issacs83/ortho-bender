cmake_minimum_required(VERSION 3.20)

project(ortho-bender-tests
    VERSION 0.1.0
    LANGUAGES C CXX
    DESCRIPTION "Ortho-Bender unit tests"
)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

enable_testing()
find_package(GTest REQUIRED)

# Shared sources
set(SHARED_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../src/shared)
set(APP_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../src/app)

add_library(ortho-bender-shared STATIC
    ${SHARED_DIR}/wire_materials.c
)
target_include_directories(ortho-bender-shared PUBLIC ${SHARED_DIR})

# ── wire_materials tests ──
add_executable(test_wire_materials test_wire_materials.cpp)
target_link_libraries(test_wire_materials GTest::GTest GTest::Main ortho-bender-shared)
add_test(NAME wire_materials COMMAND test_wire_materials)

# ── bcode validation tests ──
add_executable(test_cam_engine test_cam_engine.cpp ${APP_DIR}/cam/cam_engine.cpp)
target_include_directories(test_cam_engine PRIVATE ${APP_DIR}/cam)
target_link_libraries(test_cam_engine GTest::GTest GTest::Main ortho-bender-shared)
add_test(NAME cam_engine COMMAND test_cam_engine)
