SUMMARY = "Ortho-Bender Web Dashboard"
DESCRIPTION = "Web-based motor control and B-code editor for wire bending machine"
HOMEPAGE = "https://github.com/issacs83/ortho-bender"
LICENSE = "CLOSED"

SRC_URI = "git://github.com/issacs83/ortho-bender.git;protocol=https;branch=main"
SRCREV = "${AUTOREV}"
PV = "0.1.0+git"

S = "${WORKDIR}/git"

inherit python3-dir

RDEPENDS:${PN} = " \
    python3 \
    python3-fastapi \
    python3-uvicorn \
    python3-pyserial \
"

do_install() {
    # Install Python package
    install -d ${D}${datadir}/ortho-bender-web/ortho_bender_web
    cp -r ${S}/tools/web_ui/ortho_bender_web/* ${D}${datadir}/ortho-bender-web/ortho_bender_web/

    # Install static files
    install -d ${D}${datadir}/ortho-bender-web/static
    cp -r ${S}/tools/web_ui/static/* ${D}${datadir}/ortho-bender-web/static/

    # Install requirements
    install -m 0644 ${S}/tools/web_ui/requirements.txt ${D}${datadir}/ortho-bender-web/

    # Install launcher script
    install -d ${D}${bindir}
    install -m 0755 ${S}/tools/web_ui/run.sh ${D}${bindir}/ortho-bender-web
}

FILES:${PN} = " \
    ${datadir}/ortho-bender-web \
    ${bindir}/ortho-bender-web \
"
