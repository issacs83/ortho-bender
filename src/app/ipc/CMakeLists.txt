add_library(ortho-bender-ipc STATIC
    rpmsg_client.cpp
)

target_include_directories(ortho-bender-ipc PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/ortho-bender>
)

target_link_libraries(ortho-bender-ipc PUBLIC ortho-bender-shared)

include(GNUInstallDirs)

install(TARGETS ortho-bender-ipc
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(FILES rpmsg_client.h
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/ortho-bender
)

install(DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../../shared/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/ortho-bender
    FILES_MATCHING PATTERN "*.h"
)
