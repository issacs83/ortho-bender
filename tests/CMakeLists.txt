cmake_minimum_required(VERSION 3.20)

project(ortho-bender-tests
    VERSION 0.1.0
    LANGUAGES C CXX
    DESCRIPTION "Ortho-Bender 단위 테스트"
)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

enable_testing()

# ──────────────────────────────────────────────
# GoogleTest
#   네이티브 빌드: 설치된 libgtest-dev 를 그대로 쓴다.
#   크로스 빌드(aarch64): 호스트용 x86 라이브러리를 링크할 수 없으므로
#   /usr/src/googletest 소스를 타깃 툴체인으로 함께 빌드한다(네트워크 불필요).
# ──────────────────────────────────────────────

set(OB_GTEST_LIBS "")

if(NOT CMAKE_CROSSCOMPILING)
    find_package(GTest QUIET)
endif()

if(GTest_FOUND OR GTEST_FOUND)
    set(OB_GTEST_LIBS GTest::gtest GTest::gtest_main)
else()
    set(GTEST_SRC_DIR "/usr/src/googletest" CACHE PATH
        "GoogleTest 소스 경로 (sudo apt install googletest)")
    if(NOT EXISTS "${GTEST_SRC_DIR}/CMakeLists.txt")
        message(FATAL_ERROR
            "GoogleTest 를 찾지 못했다.\n"
            "  네이티브: sudo apt install libgtest-dev\n"
            "  크로스  : sudo apt install googletest  (소스가 ${GTEST_SRC_DIR} 에 깔린다)")
    endif()
    # gtest 자체 경고까지 -Werror 로 잡히면 빌드가 죽으므로 EXCLUDE_FROM_ALL 로 붙인다.
    add_subdirectory(${GTEST_SRC_DIR} ${CMAKE_BINARY_DIR}/googletest EXCLUDE_FROM_ALL)
    set(OB_GTEST_LIBS gtest gtest_main)
endif()

# ──────────────────────────────────────────────
# 공용 소스
# ──────────────────────────────────────────────

set(SHARED_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../src/shared)
set(APP_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../src/app)

add_library(ortho-bender-shared STATIC
    ${SHARED_DIR}/wire_materials.c
)
target_include_directories(ortho-bender-shared PUBLIC ${SHARED_DIR})

# ── 와이어 재질 테이블 테스트 ──
add_executable(test_wire_materials test_wire_materials.cpp)
target_link_libraries(test_wire_materials ${OB_GTEST_LIBS} ortho-bender-shared)
add_test(NAME wire_materials COMMAND test_wire_materials)

# ── B-code 검증 테스트 ──
add_executable(test_cam_engine test_cam_engine.cpp ${APP_DIR}/cam/cam_engine.cpp)
target_include_directories(test_cam_engine PRIVATE ${APP_DIR}/cam)
target_link_libraries(test_cam_engine ${OB_GTEST_LIBS} ortho-bender-shared)
add_test(NAME cam_engine COMMAND test_cam_engine)
