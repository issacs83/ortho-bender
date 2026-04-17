SUMMARY = "Ortho-Bender Base Package Group"
LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    ortho-bender-app \
    ortho-bender-services \
    imx-m7-demos \
    fake-hwclock \
    wireless-regdb-static \
    firmware-imx-sdma \
"
