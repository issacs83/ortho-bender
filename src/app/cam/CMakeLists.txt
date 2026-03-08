add_library(ortho-bender-cam STATIC
    cam_engine.cpp
)

target_include_directories(ortho-bender-cam PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
)

target_link_libraries(ortho-bender-cam PUBLIC ortho-bender-shared)
