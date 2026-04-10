/**
 * @file rpmsg_config.h
 * @brief RPMsg-Lite configuration for ortho-bender M7 firmware
 *
 * Included by rpmsg_default_config.h when RL_USE_CUSTOM_CONFIG == 1.
 * Defines shared memory layout, buffer sizes, and feature flags
 * matching the Linux remoteproc/virtio driver expectations.
 *
 * IEC 62304 SW Class: B
 */

#ifndef RPMSG_CONFIG_H
#define RPMSG_CONFIG_H

/**
 * Shared memory base address for RPMsg vrings.
 * Must match Linux DTS reserved-memory region and rsc_table.c RPMSG_VRING0_ADDR.
 */
#define VDEV0_VRING_BASE (0x55000000U)

/** Shared memory base used by rpmsg_lite_remote_init() */
#define RPMSG_LITE_SHMEM_BASE (VDEV0_VRING_BASE)

/** Link ID for the A53<->M7 RPMsg channel */
#define RPMSG_LITE_LINK_ID (RL_PLATFORM_IMX8MP_M7_USER_LINK_ID)

/** Name service announcement string (Linux sees this in /dev/rpmsgX) */
#define RPMSG_LITE_NS_ANNOUNCE_STRING "ortho-bender-ipc"

/**
 * Buffer payload size: must be (2^n - 16).
 * 496 bytes is default and matches Linux rpmsg_virtio driver default.
 * Our IPC messages (ipc_protocol.h) are well under this limit.
 */
#define RL_BUFFER_PAYLOAD_SIZE (496U)

/**
 * Number of buffers per direction.  8 matches rsc_table.c RPMSG_VRING_NUM_BUFFS.
 */
#define RL_BUFFER_COUNT (8U)

/** Enable zero-copy API (required for rpmsg_queue) */
#define RL_API_HAS_ZEROCOPY (1)

/** Disable static API -- we use dynamic (heap_4) for rpmsg internal alloc */
#define RL_USE_STATIC_API (0)

/** Disable environment context (saves RAM, not needed for single-instance) */
#define RL_USE_ENVIRONMENT_CONTEXT (0)

/** Disable MCMGR -- we manage MU interrupts directly via platform port */
#define RL_USE_MCMGR_IPC_ISR_HANDLER (0)

/**
 * Enable consumed buffer notification.
 * Required for RPMsg-Lite to Linux communication to unblock Linux blocking send.
 */
#define RL_ALLOW_CONSUMED_BUFFERS_NOTIFICATION (1)

#endif /* RPMSG_CONFIG_H */
