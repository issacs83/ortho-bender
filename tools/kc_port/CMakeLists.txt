cmake_minimum_required(VERSION 3.14)
project(kc_port_test
    VERSION 1.0
    DESCRIPTION "B2 bending machine test program - Linux port for i.MX8MP-EVK"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Option to disable camera (motor-only testing)
option(USE_CAMERA "Enable camera support (requires OpenCV)" ON)
option(USE_MOTOR  "Enable motor control" ON)

# Serial library
add_library(serial STATIC
    serial/serial.cpp
    serial/unix.cpp
    serial/list_ports_linux.cpp
)
target_include_directories(serial PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/serial)
target_link_libraries(serial PRIVATE pthread)

# Main executable
add_executable(kc_test kctestmain.cpp stub.cpp)
target_include_directories(kc_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(kc_test PRIVATE serial pthread)

if(USE_CAMERA)
    find_package(OpenCV REQUIRED)
    target_link_libraries(kc_test PRIVATE ${OpenCV_LIBS})
    target_include_directories(kc_test PRIVATE ${OpenCV_INCLUDE_DIRS})
    target_compile_definitions(kc_test PRIVATE USE_CAMERA)
endif()

if(USE_MOTOR)
    target_compile_definitions(kc_test PRIVATE USE_MOTOR)
endif()

# Motor-only test (no camera dependency)
add_executable(kc_test_motor_only kctestmain.cpp stub.cpp)
target_include_directories(kc_test_motor_only PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(kc_test_motor_only PRIVATE serial pthread)
target_compile_definitions(kc_test_motor_only PRIVATE USE_MOTOR)
# Note: USE_CAMERA is intentionally NOT defined for motor-only build
