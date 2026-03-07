/**
 * @file estop.h
 * @brief Emergency stop handler — dual-path (SW + HW DRV_ENN)
 * @note E-STOP must respond within < 1ms (hardware interrupt)
 *
 * Dual-path E-STOP architecture:
 *   Path 1 (SW): GPIO ISR → estop_irq_handler() → disable motion tasks
 *   Path 2 (HW): DRV_ENN line tied to TMC5160 enable pins — kills driver
 *                 output regardless of M7 firmware state
 *
 * Both paths activate simultaneously. HW path is fail-safe (active-low).
 *
 * IEC 62304 SW Class: B (safety-critical)
 */

#ifndef ESTOP_H
#define ESTOP_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Initialize E-STOP hardware interrupt and DRV_ENN GPIO
 */
void estop_init(void);

/**
 * @brief Check if E-STOP is currently active (either path)
 */
bool estop_is_active(void);

/**
 * @brief Software-triggered E-STOP
 * @note Asserts DRV_ENN (HW path) and sets SW flag
 */
void estop_trigger_sw(void);

/**
 * @brief Clear E-STOP state (only after fault is resolved)
 * @return true if cleared successfully, false if hardware E-STOP still pressed
 * @note De-asserts DRV_ENN to re-enable TMC5160 drivers
 */
bool estop_clear(void);

/**
 * @brief E-STOP ISR handler (called from GPIO interrupt)
 * @note Asserts DRV_ENN and disables all motor outputs immediately
 */
void estop_irq_handler(void);

/**
 * @brief Check HW DRV_ENN line state
 * @return true if DRV_ENN is asserted (drivers disabled)
 */
bool estop_drv_enn_active(void);

#ifdef __cplusplus
}
#endif

#endif /* ESTOP_H */
