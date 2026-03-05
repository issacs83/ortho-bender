/**
 * @file board.h
 * @brief Board-level initialization for ortho-bender i.MX8MP M7
 *
 * IEC 62304 SW Class: B
 */

#ifndef BOARD_H
#define BOARD_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Initialize board hardware (clocks, pins, peripherals)
 * @note Must be called before RTOS scheduler starts
 */
void board_init(void);

/**
 * @brief Initialize clock configuration for M7 core
 */
void board_clock_init(void);

/**
 * @brief Initialize pin muxing
 */
void board_pin_mux_init(void);

#ifdef __cplusplus
}
#endif

#endif /* BOARD_H */
