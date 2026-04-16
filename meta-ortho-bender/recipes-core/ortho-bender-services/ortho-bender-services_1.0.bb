SUMMARY = "Ortho-Bender systemd services and config files"
DESCRIPTION = "WiFi AP, SDK backend, hostapd, udhcpd, and wpa_supplicant configs"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://ortho-bender-sdk.service \
    file://ortho-bender-ap.service \
    file://wpa_supplicant-sta.service \
    file://ortho-bender-ap.conf \
    file://udhcpd-uap0.conf \
    file://wpa_supplicant-mlan0.conf \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = " \
    ortho-bender-sdk.service \
    ortho-bender-ap.service \
    wpa_supplicant-sta.service \
"
SYSTEMD_AUTO_ENABLE = "enable"

do_install() {
    # systemd service files
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/ortho-bender-sdk.service \
        ${D}${systemd_system_unitdir}/ortho-bender-sdk.service
    install -m 0644 ${WORKDIR}/ortho-bender-ap.service \
        ${D}${systemd_system_unitdir}/ortho-bender-ap.service
    install -m 0644 ${WORKDIR}/wpa_supplicant-sta.service \
        ${D}${systemd_system_unitdir}/wpa_supplicant-sta.service

    # hostapd config for AP mode
    install -d ${D}${sysconfdir}/hostapd
    install -m 0644 ${WORKDIR}/ortho-bender-ap.conf \
        ${D}${sysconfdir}/hostapd/ortho-bender-ap.conf

    # udhcpd config for AP DHCP
    install -d ${D}${sysconfdir}
    install -m 0644 ${WORKDIR}/udhcpd-uap0.conf \
        ${D}${sysconfdir}/udhcpd-uap0.conf

    # wpa_supplicant template (empty networks, API-managed)
    install -d ${D}${sysconfdir}/wpa_supplicant
    install -m 0600 ${WORKDIR}/wpa_supplicant-mlan0.conf \
        ${D}${sysconfdir}/wpa_supplicant/wpa_supplicant-mlan0.conf

    # Create lease file directory
    install -d ${D}/var/lib/misc
}

RDEPENDS:${PN} = "hostapd busybox wpa-supplicant"

FILES:${PN} += " \
    ${systemd_system_unitdir}/ortho-bender-sdk.service \
    ${systemd_system_unitdir}/ortho-bender-ap.service \
    ${systemd_system_unitdir}/wpa_supplicant-sta.service \
    ${sysconfdir}/hostapd/ortho-bender-ap.conf \
    ${sysconfdir}/udhcpd-uap0.conf \
    ${sysconfdir}/wpa_supplicant/wpa_supplicant-mlan0.conf \
    /var/lib/misc \
"
