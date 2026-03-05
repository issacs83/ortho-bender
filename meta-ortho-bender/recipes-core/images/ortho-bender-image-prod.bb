SUMMARY = "Ortho-Bender Production Image"
DESCRIPTION = "Minimal production image for ortho-bender"
LICENSE = "MIT"

inherit core-image

IMAGE_FEATURES += "splash"

IMAGE_INSTALL += " \
    packagegroup-ortho-bender-base \
    packagegroup-ortho-bender-ui \
    packagegroup-ortho-bender-ml \
"
