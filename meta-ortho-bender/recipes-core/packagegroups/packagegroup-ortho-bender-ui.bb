SUMMARY = "Ortho-Bender UI Package Group"
LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    ortho-bender-app \
    qtbase \
    qtdeclarative \
    qt3d \
"
