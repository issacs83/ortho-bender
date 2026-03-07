/**
 * @file ipc_protocol.h
 * @brief Canonical IPC protocol between A53 (Linux) and M7 (FreeRTOS)
 * @note This is the single source of truth for all A53-M7 communication.
 *       Both sides MUST include this header.
 *
 * IEC 62304 SW Class: B
 */

#ifndef ORTHO_BENDER_IPC_PROTOCOL_H
#define ORTHO_BENDER_IPC_PROTOCOL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────
 * Protocol Constants
 * ────────────────────────────────────────────── */

#define IPC_PROTOCOL_VERSION    2U
#define IPC_MAX_PAYLOAD_SIZE    1600U
#define IPC_MAGIC               0x4F425744U  /* "OBWD" - Ortho Bender Wire Device */

/* ──────────────────────────────────────────────
 * Message Types
 * ────────────────────────────────────────────── */

typedef enum {
    /* A53 -> M7: Motion commands */
    MSG_MOTION_EXECUTE_BCODE    = 0x0100,   /* Execute a B-code sequence */
    MSG_MOTION_JOG              = 0x0101,   /* Manual jog single axis */
    MSG_MOTION_HOME             = 0x0102,   /* Execute homing sequence */
    MSG_MOTION_STOP             = 0x0103,   /* Controlled stop (decelerate) */
    MSG_MOTION_ESTOP            = 0x0104,   /* Emergency stop (immediate) */
    MSG_MOTION_SET_PARAM        = 0x0105,   /* Set TMC5160/motion parameters */
    MSG_MOTION_RESET            = 0x0106,   /* Reset after fault */
    MSG_MOTION_WIRE_DETECT      = 0x0107,   /* Trigger wire insertion detection (Nudge Test) */

    /* A53 -> M7: Diagnostic commands */
    MSG_DIAG_TMC_READ           = 0x0200,   /* Read TMC5160 register */
    MSG_DIAG_TMC_WRITE          = 0x0201,   /* Write TMC5160 register */
    MSG_DIAG_TMC_DUMP           = 0x0202,   /* Dump all TMC5160 status registers */
    MSG_DIAG_GET_VERSION        = 0x0203,   /* Query M7 firmware version */

    /* A53 -> M7: Thermal control */
    MSG_THERMAL_SET_TEMP        = 0x0280,   /* Set target temperature (NiTi) */

    /* M7 -> A53: Status reports */
    MSG_STATUS_MOTION           = 0x0300,   /* Current position, velocity, state */
    MSG_STATUS_TMC              = 0x0301,   /* TMC5160 DRV_STATUS / SG_RESULT */
    MSG_STATUS_ALARM            = 0x0302,   /* Fault/alarm notification */
    MSG_STATUS_BCODE_COMPLETE   = 0x0303,   /* B-code sequence finished */
    MSG_STATUS_HEARTBEAT        = 0x0304,   /* Periodic health check */
    MSG_STATUS_HOMING_DONE      = 0x0305,   /* Homing sequence completed */
    MSG_STATUS_WIRE_DETECT      = 0x0306,   /* Wire insertion detection result */
    MSG_STATUS_VERSION          = 0x0307,   /* Firmware version response */
} ipc_msg_type_t;

/* ──────────────────────────────────────────────
 * Axis Identifiers
 * ────────────────────────────────────────────── */

typedef enum {
    AXIS_FEED       = 0,    /* L: Wire feed (linear, mm) */
    AXIS_BEND       = 1,    /* theta: Bending die (degrees) */
    AXIS_ROTATE     = 2,    /* beta: Wire rotation (degrees) — Phase 2 */
    AXIS_LIFT       = 3,    /* Lift/lower mechanism (degrees) — Phase 2 */
    AXIS_MAX        = 4,    /* Maximum axis count (compile-time) */
} axis_id_t;

/* Runtime axis mask for phase-dependent axis enable */
#define AXIS_MASK_PHASE1    ((1U << AXIS_FEED) | (1U << AXIS_BEND))
#define AXIS_MASK_PHASE2    (AXIS_MASK_PHASE1 | (1U << AXIS_ROTATE) | (1U << AXIS_LIFT))

/* ──────────────────────────────────────────────
 * Motion States
 * ────────────────────────────────────────────── */

typedef enum {
    MOTION_STATE_IDLE       = 0,
    MOTION_STATE_HOMING     = 1,
    MOTION_STATE_RUNNING    = 2,
    MOTION_STATE_JOGGING    = 3,
    MOTION_STATE_STOPPING   = 4,
    MOTION_STATE_FAULT      = 5,
    MOTION_STATE_ESTOP      = 6,
} motion_state_t;

/* ──────────────────────────────────────────────
 * Message Header (common to all messages)
 * ────────────────────────────────────────────── */

typedef struct __attribute__((packed)) {
    uint32_t        magic;          /* IPC_MAGIC */
    uint16_t        msg_type;       /* ipc_msg_type_t */
    uint16_t        payload_len;    /* Length of payload in bytes */
    uint32_t        sequence;       /* Monotonic sequence number */
    uint64_t        timestamp_us;   /* Microsecond timestamp (64-bit, no overflow) */
    uint32_t        crc32;          /* CRC-32 over header (excl crc32) + payload */
} ipc_msg_header_t;

/* ──────────────────────────────────────────────
 * Payload: Motion Commands
 * ────────────────────────────────────────────── */

/* Single B-code step (IPC-optimized, no compensated field) */
typedef struct __attribute__((packed)) {
    float   L_mm;           /* Feed length (mm) */
    float   beta_deg;       /* Rotation angle (degrees), 0 in Phase 1 */
    float   theta_deg;      /* Bend angle (degrees, post-compensation) */
} bcode_step_t;

#define BCODE_SEQUENCE_MAX_STEPS    128

/* MSG_MOTION_EXECUTE_BCODE payload */
typedef struct __attribute__((packed)) {
    uint16_t        step_count;
    uint16_t        material_id;    /* wire_material_t */
    float           wire_diameter_mm;
    bcode_step_t    steps[BCODE_SEQUENCE_MAX_STEPS];
} msg_motion_bcode_t;

/* MSG_MOTION_JOG payload */
typedef struct __attribute__((packed)) {
    uint8_t     axis;           /* axis_id_t */
    int8_t      direction;      /* +1 or -1 */
    float       speed;          /* mm/s or deg/s */
    float       distance;       /* mm or degrees (0 = continuous) */
} msg_motion_jog_t;

/* MSG_MOTION_SET_PARAM payload (TMC5160 motion parameters) */
typedef struct __attribute__((packed)) {
    uint8_t     axis;           /* axis_id_t */
    uint32_t    vmax;           /* TMC5160 VMAX register value */
    uint32_t    amax;           /* TMC5160 AMAX register value */
    uint32_t    dmax;           /* TMC5160 DMAX register value */
    uint16_t    ihold;          /* Hold current (0-31) */
    uint16_t    irun;           /* Run current (0-31) */
    uint16_t    sg_threshold;   /* StallGuard2 threshold */
} msg_motion_param_t;

/* MSG_MOTION_HOME payload */
typedef struct __attribute__((packed)) {
    uint8_t     axis_mask;      /* Bitmask of axes to home (0 = all enabled) */
} msg_motion_home_t;

/* ──────────────────────────────────────────────
 * Payload: Diagnostic Commands
 * ────────────────────────────────────────────── */

/* MSG_DIAG_TMC_READ / MSG_DIAG_TMC_WRITE payload */
typedef struct __attribute__((packed)) {
    uint8_t     axis;           /* axis_id_t (selects TMC5160 chip) */
    uint8_t     reg_addr;       /* TMC5160 register address */
    uint32_t    reg_value;      /* Register value (write) or response (read) */
} msg_diag_tmc_t;

/* ──────────────────────────────────────────────
 * Payload: Thermal Control
 * ────────────────────────────────────────────── */

/* MSG_THERMAL_SET_TEMP payload */
typedef struct __attribute__((packed)) {
    float       target_celsius;     /* Target temperature */
    uint8_t     heater_enable;      /* 0=off, 1=on */
} msg_thermal_temp_t;

/* ──────────────────────────────────────────────
 * Payload: Status Reports
 * ────────────────────────────────────────────── */

/* MSG_STATUS_MOTION payload */
typedef struct __attribute__((packed)) {
    uint8_t     state;              /* motion_state_t */
    float       position[AXIS_MAX]; /* Current position per axis */
    float       velocity[AXIS_MAX]; /* Current velocity per axis */
    uint16_t    current_step;       /* B-code step index (during execution) */
    uint16_t    total_steps;        /* Total steps in current sequence */
    uint8_t     axis_mask;          /* Active axes bitmask */
} msg_status_motion_t;

/* MSG_STATUS_TMC payload (TMC5160 diagnostic data) */
typedef struct __attribute__((packed)) {
    uint32_t    drv_status[AXIS_MAX];   /* TMC5160 DRV_STATUS per axis */
    uint16_t    sg_result[AXIS_MAX];    /* StallGuard2 result per axis */
    uint16_t    cs_actual[AXIS_MAX];    /* Actual motor current per axis */
    int32_t     xactual[AXIS_MAX];      /* TMC5160 XACTUAL (step position) */
} msg_status_tmc_t;

/* MSG_STATUS_ALARM payload */
typedef struct __attribute__((packed)) {
    uint32_t    alarm_code;         /* error_code_t from error_codes.h */
    uint8_t     severity;           /* 0=warning, 1=fault, 2=critical */
    uint8_t     axis;               /* axis_id_t (0xFF if system-level) */
} msg_status_alarm_t;

/* MSG_STATUS_HEARTBEAT payload */
typedef struct __attribute__((packed)) {
    uint32_t    uptime_ms;          /* M7 uptime */
    uint8_t     state;              /* motion_state_t */
    uint16_t    active_alarms;      /* Number of active alarms */
    uint8_t     watchdog_ok;        /* 1 = WDT healthy */
    uint8_t     axis_mask;          /* Active axes bitmask */
} msg_status_heartbeat_t;

/* MSG_STATUS_WIRE_DETECT payload */
typedef struct __attribute__((packed)) {
    uint8_t     detected;           /* 1 = wire present */
    uint16_t    sg_value;           /* StallGuard reading during nudge */
} msg_status_wire_detect_t;

/* MSG_STATUS_VERSION payload */
typedef struct __attribute__((packed)) {
    uint8_t     major;
    uint8_t     minor;
    uint8_t     patch;
    uint8_t     reserved;
    uint32_t    build_timestamp;    /* Unix timestamp of build */
} msg_status_version_t;

/* ──────────────────────────────────────────────
 * Complete IPC Message
 * ────────────────────────────────────────────── */

typedef struct __attribute__((packed)) {
    ipc_msg_header_t    header;
    uint8_t             payload[IPC_MAX_PAYLOAD_SIZE];
} ipc_message_t;

/* ──────────────────────────────────────────────
 * Validation Helpers
 * ────────────────────────────────────────────── */

static inline int ipc_msg_type_valid(uint16_t type)
{
    return (type >= 0x0100 && type <= 0x0107) ||    /* Motion */
           (type >= 0x0200 && type <= 0x0203) ||    /* Diagnostic */
           (type == 0x0280) ||                       /* Thermal */
           (type >= 0x0300 && type <= 0x0307);       /* Status */
}

static inline int ipc_axis_valid(uint8_t axis, uint8_t axis_mask)
{
    return (axis < AXIS_MAX) && (axis_mask & (1U << axis));
}

#ifdef __cplusplus
}
#endif

#endif /* ORTHO_BENDER_IPC_PROTOCOL_H */
