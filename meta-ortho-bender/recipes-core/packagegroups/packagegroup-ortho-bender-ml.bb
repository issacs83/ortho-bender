SUMMARY = "Ortho-Bender ML Package Group"
LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    ortho-bender-npu \
    tensorflow-lite \
"
