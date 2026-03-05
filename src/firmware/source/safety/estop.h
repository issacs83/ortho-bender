/**
 * @file estop.h
 * @brief Emergency stop handler
 * @note E-STOP must respond within < 1ms (hardware interrupt)
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
 * @brief Initialize E-STOP hardware interrupt
 */
void estop_init(void);

/**
 * @brief Check if E-STOP is currently active
 */
bool estop_is_active(void);

/**
 * @brief Software-triggered E-STOP
 */
void estop_trigger_sw(void);

/**
 * @brief Clear E-STOP state (only after fault is resolved)
 * @return true if cleared successfully, false if hardware E-STOP still pressed
 */
bool estop_clear(void);

/**
 * @brief E-STOP ISR handler (called from GPIO interrupt)
 * @note This function disables all motor outputs immediately
 */
void estop_irq_handler(void);

#ifdef __cplusplus
}
#endif

#endif /* ESTOP_H */
