/**
 * @file rsc_table.c
 * @brief Remoteproc resource table for i.MX8MP M7 core
 *
 * The Linux remoteproc framework requires a resource table in the firmware ELF
 * placed in a dedicated section ".resource_table".  This table declares the
 * shared resources between A53 (Linux) and M7 (FreeRTOS):
 *
 *   - VDEV (virtio device) for RPMsg transport
 *   - VRING descriptors for TX and RX ring buffers
 *
 * The resource table must be present even if RPMsg is not yet functional;
 * without it, the remoteproc driver will refuse to boot the firmware.
 *
 * Reference: Linux kernel drivers/remoteproc/remoteproc_core.c
 *            MCUXpresso SDK rsc_table.c examples
 *
 * IEC 62304 SW Class: B
 */

#include <stdint.h>
#include <stddef.h>  /* offsetof */

/* ======================================================================
 * Resource Table Types (from Linux include/uapi/linux/remoteproc.h)
 * ====================================================================== */

/* Resource types */
#define RSC_CARVEOUT    0U
#define RSC_DEVMEM      1U
#define RSC_TRACE       2U
#define RSC_VDEV        3U

/* Virtio device IDs */
#define VIRTIO_ID_RPMSG 7U

/* Feature bits */
#define VIRTIO_RPMSG_F_NS   0U  /* Name service announcement support */

/* Alignment requirements */
#define VRING_ALIGN     0x1000U

/* VirtIO ring buffer configuration */
#define VDEV_NUM_VRINGS         2U
#define RPMSG_VRING_NUM_BUFFS   8U
#define RPMSG_VRING0_ADDR       0x55000000U  /* Match Linux DTS reserved memory */
#define RPMSG_VRING1_ADDR       0x55008000U

/** Firmware resource entry: virtio ring descriptor */
struct fw_rsc_vdev_vring {
    uint32_t    da;         /**< Device address of the vring */
    uint32_t    align;      /**< Alignment requirement */
    uint32_t    num;        /**< Number of buffers */
    uint32_t    notifyid;   /**< Notify ID (doorbell) */
    uint32_t    reserved;   /**< Reserved, must be 0 */
};

/** Firmware resource entry: virtio device */
struct fw_rsc_vdev {
    uint32_t    type;           /**< RSC_VDEV */
    uint32_t    id;             /**< Virtio device ID */
    uint32_t    notifyid;       /**< Notify ID */
    uint32_t    dfeatures;      /**< Device features */
    uint32_t    gfeatures;      /**< Guest (negotiated) features */
    uint32_t    config_len;     /**< Config space length */
    uint8_t     status;         /**< Virtio status */
    uint8_t     num_of_vrings;  /**< Number of vrings */
    uint8_t     reserved[2];    /**< Reserved padding */
    struct fw_rsc_vdev_vring vring[2];  /**< Two vrings: TX + RX */
};

/** Top-level resource table with one VDEV entry for RPMsg */
struct remote_resource_table {
    uint32_t    version;        /**< Resource table version (must be 1) */
    uint32_t    num;            /**< Number of resource entries */
    uint32_t    reserved[2];    /**< Reserved, must be 0 */
    uint32_t    offset[1];      /**< Offset to each resource entry */
    struct fw_rsc_vdev  rpmsg_vdev; /**< RPMsg virtio device */
};

/* ======================================================================
 * Resource Table Instance
 *
 * Placed in ".resource_table" section so the Linux remoteproc loader
 * can find it in the ELF.
 * ====================================================================== */

__attribute__((section(".resource_table"), used))
struct remote_resource_table resources = {
    .version    = 1U,
    .num        = 1U,                       /* One resource: RPMsg VDEV */
    .reserved   = {0U, 0U},
    .offset     = {
        offsetof(struct remote_resource_table, rpmsg_vdev),
    },
    .rpmsg_vdev = {
        .type           = RSC_VDEV,
        .id             = VIRTIO_ID_RPMSG,
        .notifyid       = 0U,
        .dfeatures      = (1U << VIRTIO_RPMSG_F_NS),
        .gfeatures      = 0U,
        .config_len     = 0U,
        .status         = 0U,
        .num_of_vrings  = VDEV_NUM_VRINGS,
        .reserved       = {0U, 0U},
        .vring          = {
            [0] = {
                .da         = RPMSG_VRING0_ADDR,
                .align      = VRING_ALIGN,
                .num        = RPMSG_VRING_NUM_BUFFS,
                .notifyid   = 0U,
                .reserved   = 0U,
            },
            [1] = {
                .da         = RPMSG_VRING1_ADDR,
                .align      = VRING_ALIGN,
                .num        = RPMSG_VRING_NUM_BUFFS,
                .notifyid   = 1U,
                .reserved   = 0U,
            },
        },
    },
};

/**
 * @brief Copy of resource table for runtime use
 *
 * The remoteproc driver may modify fields (status, gfeatures) at runtime.
 * Some implementations keep a mutable copy; the const version in .resource_table
 * is the one the loader reads.
 */
void *resource_table_get(void)
{
    return (void *)&resources;
}

uint32_t resource_table_get_size(void)
{
    return sizeof(resources);
}
