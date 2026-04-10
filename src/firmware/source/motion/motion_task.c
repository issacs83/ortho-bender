/**
 * @file motion_task.c
 * @brief FreeRTOS task: 100 Hz trajectory sequence manager
 * @author ortho-bender firmware team
 *
 * Converts B-code sequences received via IPC into STEP/DIR motor commands.
 * Each B-code step executes axes sequentially: FEED -> BEND (-> ROTATE -> LIFT
 * in Phase 2).  The M7 generates STEP pulses via GPT timers (step_gen.c);
 * TMC260C-PA handles current chopping and diagnostics (tmc260c.c).
 *
 * Memory: ~200 bytes static (.bss), 0 bytes dynamic allocation
 * Stack:  1024 words (from main.c STACK_MOTION)
 *
 * IEC 62304 SW Class: B (safety-critical motion control)
 */

#include <string.h>

#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"
#include "semphr.h"

#include "motion_controller.h"
#include "tmc260c.h"
#include "step_gen.h"
#include "hal_gpio.h"
#include "machine_config.h"
#include "ipc_protocol.h"
#include "error_codes.h"
#include "estop.h"

/* ──────────────────────────────────────────────
 * Constants
 * ────────────────────────────────────────────── */

/** Maximum ticks to wait for position reached before timeout */
#define MOTION_STEP_TIMEOUT_MS      30000U

/** Queue depth for incoming motion commands */
#define MOTION_CMD_QUEUE_DEPTH      4U

/** Position tolerance in microsteps for "reached" confirmation */
#define MOTION_POS_TOLERANCE_USTEPS 2

/* ──────────────────────────────────────────────
 * Per-axis velocity/accel defaults (in step frequency / steps per s^2)
 *
 * Computed from machine_config.h geometry:
 *   step_freq = speed_in_units * usteps_per_unit [* gear_ratio]
 *   accel_freq = accel_in_units * usteps_per_unit [* gear_ratio]
 * ────────────────────────────────────────────── */

/** FEED: 50 mm/s * 3200 usteps/mm = 160,000 steps/s */
#define FEED_DEFAULT_FREQ       ((uint32_t)(FEED_MAX_SPEED_MM_S * FEED_USTEPS_PER_MM))
/** FEED accel: 200 mm/s^2 * 3200 = 640,000 steps/s^2 */
#define FEED_DEFAULT_ACCEL      ((uint32_t)(FEED_MAX_ACCEL_MM_S2 * FEED_USTEPS_PER_MM))

/** BEND: 90 deg/s * 8.889 usteps/deg * 20 gear = 16,000 steps/s */
#define BEND_DEFAULT_FREQ       ((uint32_t)(BEND_MAX_SPEED_DEG_S * BEND_USTEPS_PER_DEG * BEND_GEAR_RATIO))
/** BEND accel: 360 deg/s^2 * 8.889 * 20 = 64,000 steps/s^2 */
#define BEND_DEFAULT_ACCEL      ((uint32_t)(BEND_MAX_ACCEL_DEG_S2 * BEND_USTEPS_PER_DEG * BEND_GEAR_RATIO))

/** ROTATE: 180 deg/s * 8.889 * 16 gear = 25,600 steps/s */
#define ROTATE_DEFAULT_FREQ     ((uint32_t)(ROTATE_MAX_SPEED_DEG_S * ROTATE_USTEPS_PER_DEG * ROTATE_GEAR_RATIO))
/** ROTATE accel: 720 * 8.889 * 16 = 102,400 steps/s^2 */
#define ROTATE_DEFAULT_ACCEL    ((uint32_t)(ROTATE_MAX_ACCEL_DEG_S2 * ROTATE_USTEPS_PER_DEG * ROTATE_GEAR_RATIO))

/** LIFT: 90 deg/s * 8.889 * 10 gear = 8,000 steps/s */
#define LIFT_DEFAULT_FREQ       ((uint32_t)(LIFT_MAX_SPEED_DEG_S * LIFT_USTEPS_PER_DEG * LIFT_GEAR_RATIO))
/** LIFT accel: 360 * 8.889 * 10 = 32,000 steps/s^2 */
#define LIFT_DEFAULT_ACCEL      ((uint32_t)(LIFT_MAX_ACCEL_DEG_S2 * LIFT_USTEPS_PER_DEG * LIFT_GEAR_RATIO))

/* ──────────────────────────────────────────────
 * Per-axis runtime parameters (modifiable via SET_PARAM)
 * ────────────────────────────────────────────── */

static uint32_t s_axis_freq[AXIS_MAX]  = {
    FEED_DEFAULT_FREQ, BEND_DEFAULT_FREQ,
    ROTATE_DEFAULT_FREQ, LIFT_DEFAULT_FREQ
};
static uint32_t s_axis_accel[AXIS_MAX] = {
    FEED_DEFAULT_ACCEL, BEND_DEFAULT_ACCEL,
    ROTATE_DEFAULT_ACCEL, LIFT_DEFAULT_ACCEL
};

/* ──────────────────────────────────────────────
 * Motion Command Envelope (internal)
 * ────────────────────────────────────────────── */

typedef enum {
    MCMD_EXECUTE_BCODE  = 0,
    MCMD_JOG            = 1,
    MCMD_HOME           = 2,
    MCMD_STOP           = 3,
    MCMD_ESTOP          = 4,
    MCMD_RESET          = 5,
    MCMD_SET_PARAM      = 6,
    MCMD_WIRE_DETECT    = 7,
} motion_cmd_id_t;

typedef struct {
    motion_cmd_id_t cmd;
    union {
        msg_motion_bcode_t  bcode;
        msg_motion_jog_t    jog;
        msg_motion_home_t   home;
        msg_motion_param_t  param;
    } data;
} motion_cmd_t;

/* ──────────────────────────────────────────────
 * Module State (static allocation -- MISRA compliant)
 * ────────────────────────────────────────────── */

/** Command queue: ipc_task enqueues, motion_task dequeues */
static StaticQueue_t        s_cmd_queue_buf;
static uint8_t              s_cmd_queue_storage[MOTION_CMD_QUEUE_DEPTH * sizeof(motion_cmd_t)];
static QueueHandle_t        s_cmd_queue;

/** Current motion state */
static volatile motion_state_t  s_state = MOTION_STATE_IDLE;

/** Current B-code execution progress */
static volatile uint16_t    s_current_step  = 0;
static volatile uint16_t    s_total_steps   = 0;

/** Current axis positions in user units (mm or degrees) */
static float                s_positions[AXIS_MAX] = {0};

/** Active axis mask (Phase 1: FEED + BEND only) */
static uint8_t              s_axis_mask = AXIS_MASK_PHASE1;

/** TMC260C-PA driver instances (one per axis, static allocation) */
static tmc260c_t            s_tmc[AXIS_MAX];

/* ──────────────────────────────────────────────
 * Forward Declarations (internal helpers)
 * ────────────────────────────────────────────── */

static error_code_t motion_execute_sequence(const msg_motion_bcode_t *bcode);
static error_code_t motion_execute_single_step(const bcode_step_t *step, uint16_t step_idx);
static error_code_t motion_move_axis_and_wait(uint8_t axis, int32_t target_usteps);
static int32_t      motion_mm_to_usteps(float mm);
static int32_t      motion_deg_to_usteps_bend(float deg);
static int32_t      motion_deg_to_usteps_rotate(float deg);
static void         motion_send_bcode_complete(uint16_t steps_done, error_code_t result);
static void         motion_send_alarm(error_code_t code, uint8_t severity, uint8_t axis);
static bool         motion_check_estop(void);
static void         motion_handle_jog(const msg_motion_jog_t *jog);
static void         motion_handle_stop(void);
static void         motion_handle_set_param(const msg_motion_param_t *params);

/* ──────────────────────────────────────────────
 * TMC260C-PA CS pin mapping
 * ────────────────────────────────────────────── */

static const uint8_t s_tmc_cs_pins[AXIS_MAX] = {
    HAL_GPIO_TMC_SPI_CS0,
    HAL_GPIO_TMC_SPI_CS1,
    HAL_GPIO_TMC_SPI_CS2,
    HAL_GPIO_TMC_SPI_CS3,
};

/* ──────────────────────────────────────────────
 * Public: Queue Handle Accessor (used by ipc_task)
 * ────────────────────────────────────────────── */

QueueHandle_t motion_get_cmd_queue(void)
{
    return s_cmd_queue;
}

/* ──────────────────────────────────────────────
 * Public: motion_controller.h implementations
 * ────────────────────────────────────────────── */

error_code_t motion_init(void)
{
    s_cmd_queue = xQueueCreateStatic(
        MOTION_CMD_QUEUE_DEPTH,
        sizeof(motion_cmd_t),
        s_cmd_queue_storage,
        &s_cmd_queue_buf
    );

    if (s_cmd_queue == NULL) {
        return ERR_NOT_INITIALIZED;
    }

    s_state = MOTION_STATE_IDLE;
    s_current_step = 0;
    s_total_steps = 0;
    (void)memset(s_positions, 0, sizeof(s_positions));

    /* Initialize step pulse generator (GPT timers + STEP/DIR GPIOs) */
    if (!step_gen_init(TMC260C_AXIS_COUNT)) {
        return ERR_NOT_INITIALIZED;
    }

    /* Initialize TMC260C-PA drivers via SPI */
    for (uint8_t i = 0U; i < TMC260C_AXIS_COUNT; i++) {
        if (!tmc260c_init(&s_tmc[i], i, s_tmc_cs_pins[i])) {
            return ERR_NOT_INITIALIZED;
        }
    }

    /* Initialize E-STOP hardware */
    estop_init();

    return ERR_NONE;
}

motion_state_t motion_get_state(void)
{
    return s_state;
}

void motion_get_positions(float positions[AXIS_MAX])
{
    taskENTER_CRITICAL();
    (void)memcpy(positions, s_positions, sizeof(s_positions));
    taskEXIT_CRITICAL();
}

void motion_estop(void)
{
    s_state = MOTION_STATE_ESTOP;

    /* Immediately stop all STEP pulse generation */
    step_gen_stop_all();

    /* Assert DRV_ENN via E-STOP HW path */
    estop_trigger_sw();
}

error_code_t motion_stop(void)
{
    if (s_state == MOTION_STATE_ESTOP) {
        return ERR_MOTION_ESTOP_ACTIVE;
    }

    s_state = MOTION_STATE_STOPPING;

    /* Stop all axes (immediate, no deceleration) */
    step_gen_stop_all();

    s_state = MOTION_STATE_IDLE;
    return ERR_NONE;
}

error_code_t motion_reset(void)
{
    if (estop_is_active()) {
        if (!estop_clear()) {
            return ERR_MOTION_ESTOP_ACTIVE;
        }
    }

    /* Re-initialize TMC260C-PA drivers (clears faults via SPI re-config) */
    for (uint8_t i = 0U; i < TMC260C_AXIS_COUNT; i++) {
        (void)tmc260c_init(&s_tmc[i], i, s_tmc_cs_pins[i]);
    }

    s_state = MOTION_STATE_IDLE;
    s_current_step = 0;
    s_total_steps = 0;

    return ERR_NONE;
}

error_code_t motion_set_params(const msg_motion_param_t *params)
{
    if (params == NULL) {
        return ERR_INVALID_PARAM;
    }
    if (params->axis >= AXIS_MAX) {
        return ERR_INVALID_PARAM;
    }

    uint8_t axis = params->axis;

    /* Check axis is enabled */
    if ((s_axis_mask & (1U << axis)) == 0U) {
        return ERR_MOTION_AXIS_DISABLED;
    }

    /* Update step frequency and acceleration for this axis */
    if (params->vmax > 0U) {
        s_axis_freq[axis] = params->vmax;
    }
    if (params->amax > 0U) {
        s_axis_accel[axis] = params->amax;
    }

    /* Update TMC260C-PA current setting */
    if (params->irun > 0U) {
        tmc260c_set_current(&s_tmc[axis], (uint8_t)params->irun);
    }

    /* Update StallGuard2 threshold */
    tmc260c_set_stallguard(&s_tmc[axis], (int8_t)params->sg_threshold, true);

    return ERR_NONE;
}

void motion_tick(void)
{
    /* Update cached positions from step_gen position counters */
    for (uint8_t i = 0U; i < TMC260C_AXIS_COUNT; i++) {
        int32_t xactual = step_gen_get_position(i);

        switch (i) {
        case AXIS_FEED:
            s_positions[i] = (float)xactual / FEED_USTEPS_PER_MM;
            break;
        case AXIS_BEND:
            s_positions[i] = (float)xactual / (BEND_USTEPS_PER_DEG * BEND_GEAR_RATIO);
            break;
        case AXIS_ROTATE:
            s_positions[i] = (float)xactual / (ROTATE_USTEPS_PER_DEG * ROTATE_GEAR_RATIO);
            break;
        case AXIS_LIFT:
            s_positions[i] = (float)xactual / (LIFT_USTEPS_PER_DEG * LIFT_GEAR_RATIO);
            break;
        default:
            break;
        }
    }
}

/* ──────────────────────────────────────────────
 * Unit Conversion Helpers
 * ────────────────────────────────────────────── */

static int32_t motion_mm_to_usteps(float mm)
{
    return (int32_t)(mm * FEED_USTEPS_PER_MM);
}

static int32_t motion_deg_to_usteps_bend(float deg)
{
    return (int32_t)(deg * BEND_USTEPS_PER_DEG * BEND_GEAR_RATIO);
}

static int32_t motion_deg_to_usteps_rotate(float deg)
{
    return (int32_t)(deg * ROTATE_USTEPS_PER_DEG * ROTATE_GEAR_RATIO);
}

/* ──────────────────────────────────────────────
 * E-STOP Check (called every loop iteration)
 * ────────────────────────────────────────────── */

static bool motion_check_estop(void)
{
    if (estop_is_active()) {
        s_state = MOTION_STATE_ESTOP;
        return true;
    }
    return false;
}

/* ──────────────────────────────────────────────
 * Axis Move and Wait
 * ────────────────────────────────────────────── */

/**
 * @brief Command a single axis to target position and block until reached
 * @param axis Axis identifier
 * @param target_usteps Target position in microsteps (absolute)
 * @return ERR_NONE on success, ERR_TIMEOUT or ERR_MOTION_ESTOP_ACTIVE
 *
 * Computes the delta from current position, starts step_gen, and polls
 * for completion.  Checks E-STOP and TMC260C faults every 10 ms.
 */
static error_code_t motion_move_axis_and_wait(uint8_t axis, int32_t target_usteps)
{
    if (axis >= TMC260C_AXIS_COUNT) {
        return ERR_MOTION_AXIS_DISABLED;
    }

    /* Compute relative step count from current position */
    int32_t current_pos = step_gen_get_position(axis);
    int32_t delta = target_usteps - current_pos;

    /* Zero move: already at target */
    if (delta == 0) {
        return ERR_NONE;
    }

    /* Start trapezoidal move */
    if (!step_gen_move(axis, delta, s_axis_freq[axis], s_axis_accel[axis])) {
        return ERR_MOTION_AXIS_DISABLED;
    }

    const TickType_t poll_period = pdMS_TO_TICKS(10);
    const TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(MOTION_STEP_TIMEOUT_MS);

    while (xTaskGetTickCount() < deadline) {
        vTaskDelay(poll_period);

        /* E-STOP check every iteration */
        if (motion_check_estop()) {
            step_gen_stop(axis);
            return ERR_MOTION_ESTOP_ACTIVE;
        }

        /* TMC260C-PA fault check (poll status via SPI) */
        (void)tmc260c_read_status(&s_tmc[axis]);
        if (tmc260c_has_fault(&s_tmc[axis])) {
            step_gen_stop(axis);
            s_state = MOTION_STATE_FAULT;
            motion_send_alarm(ERR_TMC_DRIVER_ERROR, 2U, axis);
            return ERR_TMC_DRIVER_ERROR;
        }

        /* Step generation complete? */
        if (step_gen_is_complete(axis)) {
            return ERR_NONE;
        }
    }

    /* Timeout -- stop axis and report */
    step_gen_stop(axis);
    motion_send_alarm(ERR_TIMEOUT, 1U, axis);
    return ERR_TIMEOUT;
}

/* ──────────────────────────────────────────────
 * B-code Step Execution
 * ────────────────────────────────────────────── */

/**
 * @brief Execute one B-code step: FEED -> BEND (-> ROTATE -> LIFT in Phase 2)
 * @param step B-code step data
 * @param step_idx Step index for progress reporting
 * @return ERR_NONE on success
 */
static error_code_t motion_execute_single_step(const bcode_step_t *step,
                                                uint16_t step_idx)
{
    error_code_t rc = ERR_NONE;

    s_current_step = step_idx;

    /* --- Phase 2: ROTATE axis (beta) --- */
    if ((s_axis_mask & (1U << AXIS_ROTATE)) != 0U) {
        if (step->beta_deg != 0.0f) {
            int32_t delta = motion_deg_to_usteps_rotate(step->beta_deg);
            /* Rotate is relative -- add to current position */
            int32_t target = step_gen_get_position(AXIS_ROTATE) + delta;
            rc = motion_move_axis_and_wait(AXIS_ROTATE, target);
            if (rc != ERR_NONE) {
                return rc;
            }
        }
    }

    /* --- FEED axis (L_mm) --- */
    if (step->L_mm > 0.0f) {
        int32_t delta = motion_mm_to_usteps(step->L_mm);
        /* Feed is relative -- add to current position */
        int32_t target = step_gen_get_position(AXIS_FEED) + delta;
        rc = motion_move_axis_and_wait(AXIS_FEED, target);
        if (rc != ERR_NONE) {
            return rc;
        }
    }

    /* --- BEND axis (theta_deg) --- */
    if (step->theta_deg != 0.0f) {
        int32_t target = motion_deg_to_usteps_bend(step->theta_deg);
        /* Bend is absolute from zero -- bend, then return to 0 */
        rc = motion_move_axis_and_wait(AXIS_BEND, target);
        if (rc != ERR_NONE) {
            return rc;
        }

        /* Return bend die to home (0) after each bend */
        rc = motion_move_axis_and_wait(AXIS_BEND, 0);
        if (rc != ERR_NONE) {
            return rc;
        }
    }

    return ERR_NONE;
}

/* ──────────────────────────────────────────────
 * B-code Sequence Execution
 * ────────────────────────────────────────────── */

/**
 * @brief Execute a complete B-code sequence
 * @param bcode B-code data from IPC message
 * @return ERR_NONE if all steps completed successfully
 */
static error_code_t motion_execute_sequence(const msg_motion_bcode_t *bcode)
{
    if (bcode->step_count == 0U || bcode->step_count > BCODE_SEQUENCE_MAX_STEPS) {
        return ERR_MOTION_INVALID_BCODE;
    }

    s_state = MOTION_STATE_RUNNING;
    s_total_steps = bcode->step_count;
    s_current_step = 0;

    error_code_t rc = ERR_NONE;

    for (uint16_t i = 0; i < bcode->step_count; i++) {
        /* E-STOP check before each step */
        if (motion_check_estop()) {
            rc = ERR_MOTION_ESTOP_ACTIVE;
            break;
        }

        rc = motion_execute_single_step(&bcode->steps[i], i);
        if (rc != ERR_NONE) {
            break;
        }
    }

    /* Report completion to A53 */
    motion_send_bcode_complete(s_current_step, rc);

    if (rc == ERR_NONE) {
        s_state = MOTION_STATE_IDLE;
    }
    /* On error, state is already set (FAULT or ESTOP) */

    return rc;
}

/* ──────────────────────────────────────────────
 * Jog Handler
 * ────────────────────────────────────────────── */

static void motion_handle_jog(const msg_motion_jog_t *jog)
{
    if (jog->axis >= AXIS_MAX) {
        return;
    }
    if ((s_axis_mask & (1U << jog->axis)) == 0U) {
        return;
    }

    uint8_t axis = jog->axis;
    s_state = MOTION_STATE_JOGGING;

    if (jog->distance == 0.0f) {
        /* Continuous jog: velocity mode */
        int32_t freq = (int32_t)jog->speed;
        if (jog->direction < 0) {
            freq = -freq;
        }
        (void)step_gen_velocity_mode(axis, freq, s_axis_accel[axis]);
    } else {
        /* Distance jog: position mode */
        int32_t delta = 0;
        switch (axis) {
        case AXIS_FEED:
            delta = motion_mm_to_usteps(jog->distance);
            break;
        case AXIS_BEND:
            delta = motion_deg_to_usteps_bend(jog->distance);
            break;
        case AXIS_ROTATE:
            delta = motion_deg_to_usteps_rotate(jog->distance);
            break;
        default:
            break;
        }

        if (jog->direction < 0) {
            delta = -delta;
        }

        int32_t target = step_gen_get_position(axis) + delta;
        (void)motion_move_axis_and_wait(axis, target);
    }
}

/* ──────────────────────────────────────────────
 * Stop Handler
 * ────────────────────────────────────────────── */

static void motion_handle_stop(void)
{
    (void)motion_stop();
}

/* ──────────────────────────────────────────────
 * Set Parameter Handler
 * ────────────────────────────────────────────── */

static void motion_handle_set_param(const msg_motion_param_t *params)
{
    (void)motion_set_params(params);
}

/* ──────────────────────────────────────────────
 * IPC Notification Helpers
 * ────────────────────────────────────────────── */

/* Defined in ipc_task.c -- sends an IPC message to A53 */
extern void ipc_send_to_a53(const ipc_message_t *msg);

/**
 * @brief Send MSG_STATUS_BCODE_COMPLETE to A53
 */
static void motion_send_bcode_complete(uint16_t steps_done, error_code_t result)
{
    ipc_message_t msg;
    (void)memset(&msg, 0, sizeof(msg));

    msg.header.magic = IPC_MAGIC;
    msg.header.msg_type = MSG_STATUS_BCODE_COMPLETE;

    /* Pack a minimal completion payload:
     * [0..1] steps_done (uint16_t)
     * [2..5] result (uint32_t)
     */
    msg.header.payload_len = 6U;
    msg.payload[0] = (uint8_t)(steps_done & 0xFFU);
    msg.payload[1] = (uint8_t)((steps_done >> 8) & 0xFFU);
    uint32_t code = (uint32_t)result;
    msg.payload[2] = (uint8_t)(code & 0xFFU);
    msg.payload[3] = (uint8_t)((code >> 8) & 0xFFU);
    msg.payload[4] = (uint8_t)((code >> 16) & 0xFFU);
    msg.payload[5] = (uint8_t)((code >> 24) & 0xFFU);

    msg.header.crc32 = ipc_compute_crc32(&msg);

    ipc_send_to_a53(&msg);
}

/**
 * @brief Send MSG_STATUS_ALARM to A53
 */
static void motion_send_alarm(error_code_t code, uint8_t severity, uint8_t axis)
{
    ipc_message_t msg;
    (void)memset(&msg, 0, sizeof(msg));

    msg.header.magic = IPC_MAGIC;
    msg.header.msg_type = MSG_STATUS_ALARM;
    msg.header.payload_len = (uint16_t)sizeof(msg_status_alarm_t);

    msg_status_alarm_t *alarm = (msg_status_alarm_t *)msg.payload;
    alarm->alarm_code = (uint32_t)code;
    alarm->severity = severity;
    alarm->axis = axis;

    msg.header.crc32 = ipc_compute_crc32(&msg);

    ipc_send_to_a53(&msg);
}

/* ──────────────────────────────────────────────
 * Task Entry Point
 * ────────────────────────────────────────────── */

/**
 * @brief Motion task: 100 Hz trajectory sequence manager
 *
 * Blocks on command queue with a 10ms timeout to maintain 100 Hz tick rate.
 * When a B-code sequence is received, executes steps sequentially.
 * E-STOP is checked every iteration.
 */
void motion_task(void *params)
{
    (void)params;

    const TickType_t tick_period = pdMS_TO_TICKS(MOTION_LOOP_PERIOD_US / 1000U);

    /* Initialize motion controller (queue, step_gen, TMC260C, E-STOP) */
    error_code_t init_rc = motion_init();
    if (init_rc != ERR_NONE) {
        /* Fatal: cannot run without motion hardware */
        for (;;) {
            vTaskDelay(pdMS_TO_TICKS(1000));
        }
    }

    motion_cmd_t cmd;

    for (;;) {
        /* Block on queue with timeout = tick period (100 Hz) */
        BaseType_t got_cmd = xQueueReceive(s_cmd_queue, &cmd, tick_period);

        /* E-STOP check every iteration regardless of command */
        if (motion_check_estop()) {
            /* Drain queue while E-STOP is active */
            continue;
        }

        /* 100 Hz tick: update cached positions */
        motion_tick();

        if (got_cmd == pdTRUE) {
            switch (cmd.cmd) {
            case MCMD_EXECUTE_BCODE:
                (void)motion_execute_sequence(&cmd.data.bcode);
                break;

            case MCMD_JOG:
                motion_handle_jog(&cmd.data.jog);
                break;

            case MCMD_HOME:
                /* TODO: Implement homing sequence (StallGuard2 coarse + microswitch fine) */
                s_state = MOTION_STATE_HOMING;
                break;

            case MCMD_STOP:
                motion_handle_stop();
                break;

            case MCMD_ESTOP:
                motion_estop();
                break;

            case MCMD_RESET:
                (void)motion_reset();
                break;

            case MCMD_SET_PARAM:
                motion_handle_set_param(&cmd.data.param);
                break;

            case MCMD_WIRE_DETECT:
                /* TODO: Implement wire insertion detection (Nudge Test) */
                break;

            default:
                /* Unknown command -- ignore */
                break;
            }
        }
    }
}
