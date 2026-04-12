/**
 * @file hal_gpio.h
 * @brief GPIO hardware abstraction layer
 * @note Platform-specific implementation provided per board.
 *
 * IEC 62304 SW Class: B
 */

#ifndef HAL_GPIO_H
#define HAL_GPIO_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** GPIO pin identifier (board-specific mapping in board.h) */
typedef enum {
    /* STEP/DIR pins for TMC260C-PA motor drivers */
    HAL_GPIO_STEP0 = 0,         /* FEED axis STEP */
    HAL_GPIO_DIR0,              /* FEED axis DIR */
    HAL_GPIO_STEP1,             /* BEND axis STEP */
    HAL_GPIO_DIR1,              /* BEND axis DIR */
    HAL_GPIO_STEP2,             /* ROTATE axis STEP (Phase 2) */
    HAL_GPIO_DIR2,              /* ROTATE axis DIR  (Phase 2) */
    HAL_GPIO_STEP3,             /* LIFT axis STEP   (Phase 2) */
    HAL_GPIO_DIR3,              /* LIFT axis DIR    (Phase 2) */

    /* TMC260C-PA SPI chip-select pins */
    HAL_GPIO_TMC_SPI_CS0,      /* FEED axis SPI CS */
    HAL_GPIO_TMC_SPI_CS1,      /* BEND axis SPI CS */
    HAL_GPIO_TMC_SPI_CS2,      /* ROTATE axis SPI CS (Phase 2) */
    HAL_GPIO_TMC_SPI_CS3,      /* LIFT axis SPI CS   (Phase 2) */

    /* TMC260C-PA diagnostic pins (active-low, directly map to StallGuard2) */
    HAL_GPIO_TMC_DIAG0,        /* FEED DIAG output */
    HAL_GPIO_TMC_DIAG1,        /* BEND DIAG output */
    HAL_GPIO_TMC_DIAG2,        /* ROTATE DIAG (Phase 2) */
    HAL_GPIO_TMC_DIAG3,        /* LIFT DIAG (Phase 2) */

    /* Safety */
    HAL_GPIO_DRV_ENN,          /* Driver enable (active-high disables, shared) */
    HAL_GPIO_ESTOP_IN,         /* E-STOP button input (active-low) */

    /* Homing */
    HAL_GPIO_HOME_BEND,        /* BEND axis microswitch */

    HAL_GPIO_COUNT
} hal_gpio_pin_t;

/** GPIO direction */
typedef enum {
    HAL_GPIO_DIR_INPUT = 0,
    HAL_GPIO_DIR_OUTPUT
} hal_gpio_dir_t;

/** GPIO interrupt edge */
typedef enum {
    HAL_GPIO_EDGE_NONE = 0,
    HAL_GPIO_EDGE_RISING,
    HAL_GPIO_EDGE_FALLING,
    HAL_GPIO_EDGE_BOTH
} hal_gpio_edge_t;

/** GPIO interrupt callback */
typedef void (*hal_gpio_callback_t)(hal_gpio_pin_t pin);

/**
 * @brief Initialize a GPIO pin
 * @param pin Pin identifier
 * @param dir Direction (input/output)
 * @param initial_value Initial output value (ignored for inputs)
 * @return true on success
 */
bool hal_gpio_init(hal_gpio_pin_t pin, hal_gpio_dir_t dir, bool initial_value);

/**
 * @brief Read GPIO pin state
 */
bool hal_gpio_read(hal_gpio_pin_t pin);

/**
 * @brief Write GPIO pin state
 */
void hal_gpio_write(hal_gpio_pin_t pin, bool value);

/**
 * @brief Toggle GPIO pin
 */
void hal_gpio_toggle(hal_gpio_pin_t pin);

/**
 * @brief Attach interrupt handler to a GPIO pin
 * @param pin Pin identifier
 * @param edge Trigger edge
 * @param callback ISR-safe callback function
 * @return true on success
 */
bool hal_gpio_irq_attach(hal_gpio_pin_t pin, hal_gpio_edge_t edge,
                         hal_gpio_callback_t callback);

/**
 * @brief Enable GPIO interrupt
 */
void hal_gpio_irq_enable(hal_gpio_pin_t pin);

/**
 * @brief Disable GPIO interrupt
 */
void hal_gpio_irq_disable(hal_gpio_pin_t pin);

#ifdef __cplusplus
}
#endif

#endif /* HAL_GPIO_H */
