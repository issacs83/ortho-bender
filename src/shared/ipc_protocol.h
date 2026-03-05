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

#define IPC_PROTOCOL_VERSION    1U
#define IPC_MAX_PAYLOAD_SIZE    256U
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
    MSG_MOTION_SET_PARAM        = 0x0105,   /* Set PID/accel parameters */
    MSG_MOTION_RESET            = 0x0106,   /* Reset after fault */

    /* A53 -> M7: Sensor commands */
    MSG_SENSOR_READ_ALL         = 0x0200,   /* Request all sensor readings */
    MSG_SENSOR_TARE_FORCE       = 0x0201,   /* Zero force sensor */
    MSG_SENSOR_SET_TEMP         = 0x0202,   /* Set target temperature (NiTi) */
    MSG_SENSOR_CALIBRATE        = 0x0203,   /* Trigger sensor calibration */

    /* M7 -> A53: Status reports */
    MSG_STATUS_MOTION           = 0x0300,   /* Current position, velocity, state */
    MSG_STATUS_SENSORS          = 0x0301,   /* Force, temperature, encoder readings */
    MSG_STATUS_ALARM            = 0x0302,   /* Fault/alarm notification */
    MSG_STATUS_BCODE_COMPLETE   = 0x0303,   /* B-code sequence finished */
    MSG_STATUS_HEARTBEAT        = 0x0304,   /* Periodic health check */
    MSG_STATUS_HOMING_DONE      = 0x0305,   /* Homing sequence completed */
} ipc_msg_type_t;

/* ──────────────────────────────────────────────
 * Axis Identifiers
 * ────────────────────────────────────────────── */

typedef enum {
    AXIS_FEED       = 0,    /* L: Wire feed (linear, mm) */
    AXIS_ROTATE     = 1,    /* beta: Wire rotation (degrees) */
    AXIS_BEND       = 2,    /* theta: Bending die (degrees) */
    AXIS_COUNT      = 3,
} axis_id_t;

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
    uint32_t        timestamp_us;   /* Microsecond timestamp */
} ipc_msg_header_t;

/* ──────────────────────────────────────────────
 * Payload: Motion Commands
 * ────────────────────────────────────────────── */

/* Single B-code step */
typedef struct __attribute__((packed)) {
    float   L_mm;           /* Feed length (mm) */
    float   beta_deg;       /* Rotation angle (degrees) */
    float   theta_deg;      /* Bend angle (degrees) */
} bcode_step_t;

#define BCODE_SEQUENCE_MAX_STEPS    64

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

/* MSG_MOTION_SET_PARAM payload */
typedef struct __attribute__((packed)) {
    uint8_t     axis;           /* axis_id_t */
    float       kp;             /* Proportional gain */
    float       ki;             /* Integral gain */
    float       kd;             /* Derivative gain */
    float       max_velocity;   /* mm/s or deg/s */
    float       max_accel;      /* mm/s^2 or deg/s^2 */
} msg_motion_param_t;

/* ──────────────────────────────────────────────
 * Payload: Sensor Commands
 * ────────────────────────────────────────────── */

/* MSG_SENSOR_SET_TEMP payload */
typedef struct __attribute__((packed)) {
    float       target_celsius;     /* Target temperature */
    uint8_t     heater_enable;      /* 0=off, 1=on */
} msg_sensor_temp_t;

/* ──────────────────────────────────────────────
 * Payload: Status Reports
 * ────────────────────────────────────────────── */

/* MSG_STATUS_MOTION payload */
typedef struct __attribute__((packed)) {
    uint8_t     state;              /* motion_state_t */
    float       position[AXIS_COUNT];   /* Current position per axis */
    float       velocity[AXIS_COUNT];   /* Current velocity per axis */
    uint16_t    current_step;       /* B-code step index (during execution) */
    uint16_t    total_steps;        /* Total steps in current sequence */
} msg_status_motion_t;

/* MSG_STATUS_SENSORS payload */
typedef struct __attribute__((packed)) {
    float       force_n;            /* Bending force (N) */
    float       temperature_c;      /* Wire/die temperature (Celsius) */
    int32_t     encoder_counts[AXIS_COUNT]; /* Raw encoder counts */
    uint8_t     limit_switches;     /* Bitfield: bit0=feed_home, bit1=rotate_home, bit2=bend_home */
} msg_status_sensors_t;

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
} msg_status_heartbeat_t;

/* ──────────────────────────────────────────────
 * Complete IPC Message
 * ────────────────────────────────────────────── */

typedef struct __attribute__((packed)) {
    ipc_msg_header_t    header;
    uint8_t             payload[IPC_MAX_PAYLOAD_SIZE];
} ipc_message_t;

#ifdef __cplusplus
}
#endif

#endif /* ORTHO_BENDER_IPC_PROTOCOL_H */
