SUMMARY = "Ortho-Bender A53 Application"
DESCRIPTION = "Main application for ortho-bender wire bending machine"
LICENSE = "CLOSED"

SRC_URI = "git://github.com/issacs83/ortho-bender.git;protocol=https;branch=main"
SRCREV = "${AUTOREV}"
PV = "0.1.0+git"

S = "${WORKDIR}/git"

inherit cmake

OECMAKE_SOURCEPATH = "${S}/src/app"
