add_library(ortho-bender-cam STATIC
    cam_engine.cpp
)

target_include_directories(ortho-bender-cam PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../../shared
)
