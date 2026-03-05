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
