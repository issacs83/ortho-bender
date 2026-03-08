SUMMARY = "Ortho-Bender IPC Library"
DESCRIPTION = "RPMsg IPC client library for A53-M7 communication"
LICENSE = "CLOSED"

SRC_URI = "git://github.com/issacs83/ortho-bender.git;protocol=https;branch=main"
SRCREV = "${AUTOREV}"
PV = "0.1.0+git"

S = "${WORKDIR}/git"

inherit cmake

OECMAKE_SOURCEPATH = "${S}/src/app/ipc"
