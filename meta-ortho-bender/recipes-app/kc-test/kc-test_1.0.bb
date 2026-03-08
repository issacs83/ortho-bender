# kc-test - B2 bending machine test program (Linux port for i.MX8MP-EVK)
#
# Builds the kc_test motor-only and full (with OpenCV camera) binaries,
# plus the motor_sim virtual serial simulator.
#
# IEC 62304 SW Class: N/A (test/debug tool, not part of production SW)

SUMMARY = "B2 bending machine test program for i.MX8MP-EVK"
DESCRIPTION = "Hardware verification tool ported from YOAT B2 TEST PROGRAM. \
Exercises motor axes (FEED, BEND, ROTATE, LIFT) via serial, \
and optionally captures frames from CSI/V4L2 camera."
HOMEPAGE = "https://github.com/issacs83/ortho-bender"
LICENSE = "CLOSED"

SRC_URI = "git://github.com/issacs83/ortho-bender.git;protocol=https;branch=main"
SRCREV = "${AUTOREV}"
PV = "1.0+git"

S = "${WORKDIR}/git"

inherit cmake

OECMAKE_SOURCEPATH = "${S}/tools/kc_port"

# Build both camera+motor (kc_test) and motor-only (kc_test_motor_only) targets
EXTRA_OECMAKE = "-DUSE_MOTOR=ON"

PACKAGECONFIG ??= "camera"
PACKAGECONFIG[camera] = "-DUSE_CAMERA=ON,-DUSE_CAMERA=OFF,opencv"

DEPENDS = ""

# Packages: split motor-only, full, and simulator
PACKAGES = "${PN}-motor-only ${PN} ${PN}-sim ${PN}-dbg"

FILES:${PN}-motor-only = "${bindir}/kc_test_motor_only"
FILES:${PN}            = "${bindir}/kc_test"
FILES:${PN}-sim        = "${bindir}/motor_sim"
FILES:${PN}-dbg        = "${bindir}/.debug"

RDEPENDS:${PN} = "libopencv-core libopencv-imgproc libopencv-videoio libopencv-highgui"

do_install() {
    install -d ${D}${bindir}

    if [ -f ${B}/kc_test ]; then
        install -m 0755 ${B}/kc_test ${D}${bindir}/kc_test
    fi

    if [ -f ${B}/kc_test_motor_only ]; then
        install -m 0755 ${B}/kc_test_motor_only ${D}${bindir}/kc_test_motor_only
    fi

    if [ -f ${B}/motor_sim ]; then
        install -m 0755 ${B}/motor_sim ${D}${bindir}/motor_sim
    fi
}

# motor-only variant has no external runtime deps
RDEPENDS:${PN}-motor-only = ""
RDEPENDS:${PN}-sim = ""

# Allow building motor-only without camera/OpenCV
ALLOW_EMPTY:${PN} = "1"
