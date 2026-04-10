/**
 * @file estop.c
 * @brief Emergency stop handler -- dual-path (SW + HW DRV_ENN)
 * @author ortho-bender firmware team
 *
 * Implements the E-STOP dual-path safety mechanism:
 *   Path 1 (SW): GPIO falling-edge ISR sets software flag and asserts DRV_ENN
 *   Path 2 (HW): DRV_ENN GPIO line is directly connected to TMC260C-PA enable
 *                pins -- asserting it (active-low) kills driver output
 *                regardless of firmware state
 *
 * Response time: < 1 ms from E-STOP button press to DRV_ENN assertion.
 * The ISR runs at highest NVIC priority to ensure deterministic latency.
 *
 * DRV_ENN is active-low: LOW = drivers enabled, HIGH = drivers disabled.
 *
 * Memory: 4 bytes static (.bss)
 * No dynamic memory allocation.
 *
 * IEC 62304 SW Class: B (safety-critical)
 */

#include "estop.h"
#include "hal_gpio.h"

/* ======================================================================
 * Module state (static allocation)
 * ====================================================================== */

/** Software E-STOP flag.  Set by ISR or estop_trigger_sw(), cleared by
 *  estop_clear() only after hardware button is verified released. */
static volatile bool s_estop_active = false;

/* ======================================================================
 * ISR callback (registered with hal_gpio_irq_attach)
 * ====================================================================== */

/**
 * @brief GPIO interrupt callback for E-STOP button
 *
 * Executes at highest NVIC priority.  Asserts DRV_ENN immediately.
 * Must complete in < 500 ns.  No RTOS calls allowed.
 */
static void estop_gpio_callback(hal_gpio_pin_t pin)
{
    (void)pin;

    /* Assert DRV_ENN immediately (active-high to disable drivers) */
    hal_gpio_write(HAL_GPIO_DRV_ENN, true);

    /* Set software flag */
    s_estop_active = true;
}

/* ======================================================================
 * Public API
 * ====================================================================== */

void estop_init(void)
{
    s_estop_active = false;

    /* Configure DRV_ENN as output, initially de-asserted (drivers enabled) */
    (void)hal_gpio_init(HAL_GPIO_DRV_ENN, HAL_GPIO_DIR_OUTPUT, false);

    /* Configure E-STOP button input with falling-edge interrupt.
     * E-STOP button is active-low: pressed = LOW, released = HIGH.
     * Falling edge = button press event. */
    (void)hal_gpio_init(HAL_GPIO_ESTOP_IN, HAL_GPIO_DIR_INPUT, false);
    (void)hal_gpio_irq_attach(HAL_GPIO_ESTOP_IN, HAL_GPIO_EDGE_FALLING,
                              estop_gpio_callback);
    hal_gpio_irq_enable(HAL_GPIO_ESTOP_IN);

    /* If E-STOP is already pressed at init time, trigger immediately */
    if (!hal_gpio_read(HAL_GPIO_ESTOP_IN)) {
        estop_gpio_callback(HAL_GPIO_ESTOP_IN);
    }
}

bool estop_is_active(void)
{
    return s_estop_active;
}

void estop_trigger_sw(void)
{
    /* Assert DRV_ENN (disable all drivers) */
    hal_gpio_write(HAL_GPIO_DRV_ENN, true);

    /* Set software flag */
    s_estop_active = true;
}

bool estop_clear(void)
{
    /* Verify hardware E-STOP button is released (pin HIGH) before clearing.
     * This prevents clearing E-STOP while the button is still pressed. */
    if (!hal_gpio_read(HAL_GPIO_ESTOP_IN)) {
        /* Button still pressed -- cannot clear */
        return false;
    }

    /* De-assert DRV_ENN (re-enable drivers) */
    hal_gpio_write(HAL_GPIO_DRV_ENN, false);

    /* Clear software flag */
    s_estop_active = false;

    return true;
}

void estop_irq_handler(void)
{
    /* Direct ISR entry point (for use from vector table if not using
     * hal_gpio_irq_attach callback mechanism) */
    estop_gpio_callback(HAL_GPIO_ESTOP_IN);
}

bool estop_drv_enn_active(void)
{
    return hal_gpio_read(HAL_GPIO_DRV_ENN);
}
