/**
 * @file board.h
 * @brief Board-level initialization for ortho-bender i.MX8MP M7
 *
 * IEC 62304 SW Class: B
 */

#ifndef BOARD_H
#define BOARD_H

#include <stdbool.h>
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

/**
 * @brief Enable MU interrupt early (before scheduler)
 *
 * Arms MU1_M7_IRQn so that the Linux remoteproc DRIVER_OK kick is not
 * missed.  Does NOT create any rpmsg_lite structures — full init happens
 * in rpmsg_hal_init() from ipc_task after the scheduler is running.
 */
void rpmsg_mu_init_early(void);

/**
 * @brief Initialize RPMsg transport (full init, requires scheduler running)
 * @return true on success (link up, endpoint created, NS announced)
 */
bool rpmsg_hal_init(void);

#ifdef __cplusplus
}
#endif

#endif /* BOARD_H */
