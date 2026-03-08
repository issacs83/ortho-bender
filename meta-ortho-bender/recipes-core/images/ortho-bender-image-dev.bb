SUMMARY = "Ortho-Bender Development Image"
DESCRIPTION = "Full development image with debug tools for ortho-bender"
LICENSE = "MIT"

inherit core-image

IMAGE_FEATURES += "splash ssh-server-openssh"

IMAGE_INSTALL += " \
    packagegroup-ortho-bender-base \
    packagegroup-ortho-bender-ui \
    packagegroup-ortho-bender-ml \
"

# Hardware test tools (kc_test B2 motor/camera verification)
IMAGE_INSTALL += " \
    kc-test \
    kc-test-motor-only \
    kc-test-sim \
"

# Web dashboard
IMAGE_INSTALL += " \
    ortho-bender-web \
"

# Development tools
IMAGE_INSTALL += " \
    gdb \
    strace \
    ltrace \
    can-utils \
    i2c-tools \
    spi-tools \
    python3 \
    python3-pip \
"
