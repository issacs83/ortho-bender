/**
 * @file motor_hal.c
 * @brief Unified motor driver HAL -- dispatches to driver-specific backends
 * @author ortho-bender firmware team
 *
 * Routes all motor_hal_*() calls through the function pointer vtable
 * (motor_hal_ops_t) bound at init time.  The HAL layer maintains a
 * software position counter that is driver-agnostic.
 *
 * Memory: code ~400 bytes Flash, 0 bytes static RAM (all state in motor_hal_t).
 * No dynamic memory allocation.
 *
 * IEC 62304 SW Class: B
 */

#include "motor_hal.h"

#include <stddef.h>
#include <string.h>

/* ======================================================================
 * Internal validation
 * ====================================================================== */

/**
 * @brief Validate that a motor_hal_t handle is usable
 * @param hal  Handle to validate
 * @return true if ops and drv_ctx are non-NULL
 */
static bool motor_hal_is_valid(const motor_hal_t *hal)
{
    if (hal == NULL) {
        return false;
    }
    if (hal->ops == NULL) {
        return false;
    }
    if (hal->drv_ctx == NULL) {
        return false;
    }
    return true;
}

/* ======================================================================
 * Public API
 * ====================================================================== */

motor_result_t motor_hal_init(motor_hal_t *hal)
{
    if (hal == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    if ((hal->ops == NULL) || (hal->drv_ctx == NULL)) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    if (hal->ops->init == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }

    hal->position_usteps = 0;
    hal->initialized = false;

    motor_result_t rc = hal->ops->init(hal->drv_ctx);
    if (rc == MOTOR_OK) {
        hal->initialized = true;
    }

    return rc;
}

motor_result_t motor_hal_move_abs(motor_hal_t *hal, int32_t steps,
                                  uint32_t vmax, uint32_t amax)
{
    if (!motor_hal_is_valid(hal)) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    if (!hal->initialized) {
        return MOTOR_ERR_NOT_INIT;
    }
    if (hal->ops->move_abs == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }

    motor_result_t rc = hal->ops->move_abs(hal->drv_ctx, steps, vmax, amax);
    if (rc == MOTOR_OK) {
        hal->position_usteps = steps;
    }

    return rc;
}

bool motor_hal_position_reached(motor_hal_t *hal)
{
    if (!motor_hal_is_valid(hal)) {
        return true;    /* Treat invalid handle as "no move in progress" */
    }
    if (!hal->initialized) {
        return true;
    }
    if (hal->ops->position_reached == NULL) {
        return true;
    }

    return hal->ops->position_reached(hal->drv_ctx);
}

int32_t motor_hal_get_position(motor_hal_t *hal)
{
    if (!motor_hal_is_valid(hal)) {
        return 0;
    }
    if (!hal->initialized) {
        return 0;
    }
    if (hal->ops->get_position == NULL) {
        return 0;
    }

    return hal->ops->get_position(hal->drv_ctx);
}

void motor_hal_emergency_stop(motor_hal_t *hal)
{
    if (!motor_hal_is_valid(hal)) {
        return;
    }
    /* Emergency stop works even if not initialized -- safety first */
    if (hal->ops->emergency_stop != NULL) {
        hal->ops->emergency_stop(hal->drv_ctx);
    }
}

motor_result_t motor_hal_poll_status(motor_hal_t *hal, motor_status_t *out)
{
    if (!motor_hal_is_valid(hal)) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    if (out == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    if (!hal->initialized) {
        return MOTOR_ERR_NOT_INIT;
    }
    if (hal->ops->poll_status == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }

    /* Zero the output before filling */
    (void)memset(out, 0, sizeof(motor_status_t));

    return hal->ops->poll_status(hal->drv_ctx, out);
}

void motor_hal_enable(motor_hal_t *hal)
{
    if (!motor_hal_is_valid(hal)) {
        return;
    }
    if (hal->ops->enable != NULL) {
        hal->ops->enable(hal->drv_ctx);
    }
}

void motor_hal_disable(motor_hal_t *hal)
{
    if (!motor_hal_is_valid(hal)) {
        return;
    }
    if (hal->ops->disable != NULL) {
        hal->ops->disable(hal->drv_ctx);
    }
}
