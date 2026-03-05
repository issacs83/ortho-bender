add_library(ortho-bender-ipc STATIC
    rpmsg_client.cpp
)

target_include_directories(ortho-bender-ipc PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../../shared
)
