/**
 * @file motion_controller.h
 * @brief Core motion controller state machine
 *
 * IEC 62304 SW Class: B
 */

#ifndef MOTION_CONTROLLER_H
#define MOTION_CONTROLLER_H

#include <stdint.h>
#include "ipc_protocol.h"
#include "bcode_types.h"
#include "error_codes.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────
 * Motion Controller API
 * ────────────────────────────────────────────── */

/**
 * @brief Initialize motion controller (call once at startup)
 */
error_code_t motion_init(void);

/**
 * @brief Execute a B-code sequence
 * @param bcode Pointer to B-code command from IPC
 * @return ERR_NONE on success, error code on failure
 */
error_code_t motion_execute_bcode(const msg_motion_bcode_t *bcode);

/**
 * @brief Manual jog a single axis
 */
error_code_t motion_jog(const msg_motion_jog_t *jog);

/**
 * @brief Execute homing sequence for all axes
 */
error_code_t motion_home(void);

/**
 * @brief Controlled stop (decelerate to zero)
 */
error_code_t motion_stop(void);

/**
 * @brief Emergency stop (immediate halt, no deceleration)
 */
void motion_estop(void);

/**
 * @brief Reset motion controller after fault
 */
error_code_t motion_reset(void);

/**
 * @brief Get current motion state
 */
motion_state_t motion_get_state(void);

/**
 * @brief Get current position for all axes
 * @param positions Array of AXIS_MAX floats to fill
 */
void motion_get_positions(float positions[AXIS_MAX]);

/**
 * @brief Set TMC5160 motion parameters for an axis
 */
error_code_t motion_set_params(const msg_motion_param_t *params);

/**
 * @brief Execute homing for specific axes
 * @param axis_mask Bitmask of axes to home (0 = all enabled)
 */
error_code_t motion_home_axes(uint8_t axis_mask);

/**
 * @brief Trigger wire insertion detection (Nudge Test)
 */
error_code_t motion_wire_detect(void);

/**
 * @brief Motion trajectory manager tick (called at 100 Hz from motion_task)
 */
void motion_tick(void);

#ifdef __cplusplus
}
#endif

#endif /* MOTION_CONTROLLER_H */
