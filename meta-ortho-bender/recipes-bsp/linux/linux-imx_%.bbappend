# linux-imx_%.bbappend — Ortho-Bender kernel customization
#
# Applies to any version of linux-imx matched by the wildcard %.
# Pin to a specific version (e.g., linux-imx_6.1.bbappend) once the
# upstream NXP BSP version is locked for production.
#
# Adds:
#   1. Ortho-Bender DTS source files (and their DTSI dependencies)
#   2. Kernel config fragment (ortho-bender.cfg)
#
# Author   : Ortho-Bender BSP team

FILESEXTRAPATHS:prepend := "${THISDIR}/linux-imx:"

# ---------------------------------------------------------------------------
# Source files
# ---------------------------------------------------------------------------
# DTS and all DTSI fragments are copied into the kernel source tree under
# arch/arm64/boot/dts/freescale/ by the do_configure task.
# The main DTS references the DTSIs via relative #include, so they must
# all land in the same directory.

SRC_URI += " \
    file://dts/imx8mp-ortho-bender.dts \
    file://dts/imx8mp-ortho-bender-m7.dtsi \
    file://dts/imx8mp-ortho-bender-motors.dtsi \
    file://dts/imx8mp-ortho-bender-sensors.dtsi \
    file://dts/imx8mp-ortho-bender-camera.dtsi \
    file://dts/imx8mp-ortho-bender-wifi.dtsi \
    file://fragments/ortho-bender.cfg \
"

# ---------------------------------------------------------------------------
# Kernel config fragment
# ---------------------------------------------------------------------------
# SRC_URI entries with the .cfg extension are automatically picked up by
# the kernel-yocto bbclass and merged via merge_config.sh.
# No explicit do_configure override is needed.

# ---------------------------------------------------------------------------
# DTS installation helper
# ---------------------------------------------------------------------------
# Copy DTS/DTSI files into the kernel source tree before configuration.
# The destination matches the directory expected by the Makefile:
#   arch/arm64/boot/dts/freescale/
#
# IMPORTANT: do_copy_dts must run before do_kernel_configme so that the
# DTS files exist when the kernel Makefile scans for DTB targets.

do_copy_dts() {
    local dst="${S}/arch/arm64/boot/dts/freescale"
    install -d "${dst}"
    for f in imx8mp-ortho-bender.dts \
              imx8mp-ortho-bender-m7.dtsi \
              imx8mp-ortho-bender-motors.dtsi \
              imx8mp-ortho-bender-sensors.dtsi \
              imx8mp-ortho-bender-camera.dtsi \
              imx8mp-ortho-bender-wifi.dtsi; do
        install -m 0644 "${WORKDIR}/dts/${f}" "${dst}/${f}"
    done

    # Append the ortho-bender DTB to the freescale Makefile so that
    # 'make dtbs' actually builds it.  Guard against double-insertion
    # in case bitbake re-runs the task.
    local makefile="${dst}/Makefile"
    if ! grep -q "imx8mp-ortho-bender.dtb" "${makefile}"; then
        echo "dtb-\$(CONFIG_ARCH_MXC) += imx8mp-ortho-bender.dtb" \
            >> "${makefile}"
    fi
}

addtask do_copy_dts after do_unpack before do_patch
do_copy_dts[dirs] = "${S}"
