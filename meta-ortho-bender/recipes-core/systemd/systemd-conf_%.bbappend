# Install static eth0 config for systemd-networkd.
# Replaces kernel ip= parameter to eliminate ~100s boot delay
# when Ethernet cable is not connected.

FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += " \
    file://10-eth0.network \
    file://wait-online-timeout.conf \
"

FILES:${PN} += " \
    ${sysconfdir}/systemd/network/10-eth0.network \
    ${systemd_system_unitdir}/systemd-networkd-wait-online.service.d/wait-online-timeout.conf \
"

do_install:append() {
    # eth0 static IP (non-blocking)
    install -d ${D}${sysconfdir}/systemd/network
    install -m 0644 ${WORKDIR}/10-eth0.network \
        ${D}${sysconfdir}/systemd/network/10-eth0.network

    # Cap wait-online timeout to 5s (prevents boot hang without cable)
    install -d ${D}${systemd_system_unitdir}/systemd-networkd-wait-online.service.d
    install -m 0644 ${WORKDIR}/wait-online-timeout.conf \
        ${D}${systemd_system_unitdir}/systemd-networkd-wait-online.service.d/wait-online-timeout.conf
}
