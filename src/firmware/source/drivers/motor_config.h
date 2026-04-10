/**
 * @file motor_config.h
 * @brief Per-axis motor driver type configuration
 * @author ortho-bender firmware team
 *
 * Defines which Trinamic driver IC is installed on each axis.  These defaults
 * can be overridden at compile time via -D flags or in a board-specific
 * header included before this file.
 *
 * Also provides TMC5160-family default current/ramp constants that are
 * shared across TMC5160, TMC5130, and TMC5072 drivers.
 *
 * IEC 62304 SW Class: B
 */

#ifndef MOTOR_CONFIG_H
#define MOTOR_CONFIG_H

#include "motor_hal.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ======================================================================
 * Per-Axis Driver Type (compile-time defaults, overridable)
 * ====================================================================== */

/** FEED axis (axis 0) -- default: TMC260C-PA STEP/DIR */
#ifndef AXIS_FEED_DRIVER_TYPE
#define AXIS_FEED_DRIVER_TYPE       MOTOR_DRV_TMC260C
#endif

/** BEND axis (axis 1) -- default: TMC260C-PA STEP/DIR */
#ifndef AXIS_BEND_DRIVER_TYPE
#define AXIS_BEND_DRIVER_TYPE       MOTOR_DRV_TMC260C
#endif

/** ROTATE axis (axis 2) -- default: TMC5160 SPI ramp */
#ifndef AXIS_ROTATE_DRIVER_TYPE
#define AXIS_ROTATE_DRIVER_TYPE     MOTOR_DRV_TMC5160
#endif

/** LIFT axis (axis 3) -- default: TMC5160 SPI ramp */
#ifndef AXIS_LIFT_DRIVER_TYPE
#define AXIS_LIFT_DRIVER_TYPE       MOTOR_DRV_TMC5160
#endif

/* ======================================================================
 * TMC5160/5130/5072 Shared Default Constants
 * ====================================================================== */

/** Default hold current (0-31 IHOLD_IRUN register) */
#ifndef TMC5160_IHOLD_DEFAULT
#define TMC5160_IHOLD_DEFAULT       8U
#endif

/** Default run current (0-31 IHOLD_IRUN register) */
#ifndef TMC5160_IRUN_DEFAULT
#define TMC5160_IRUN_DEFAULT        20U
#endif

/** Default hold-to-run delay (0-15 IHOLD_IRUN register) */
#ifndef TMC5160_IHOLDDELAY_DEFAULT
#define TMC5160_IHOLDDELAY_DEFAULT  6U
#endif

/* ======================================================================
 * TMC5xxx SPI Configuration
 *
 * TMC5160/5130/5072 all use 40-bit SPI (5 bytes), SPI Mode 3.
 * Shared bus with TMC260C; SPI peripheral is the same (HAL_SPI_TMC).
 * ====================================================================== */

/** SPI clock for TMC5xxx family (max 4 MHz per datasheet) */
#ifndef TMC5XXX_SPI_CLOCK_HZ
#define TMC5XXX_SPI_CLOCK_HZ       4000000U
#endif

/** SPI mode for TMC5xxx family */
#ifndef TMC5XXX_SPI_MODE
#define TMC5XXX_SPI_MODE            3U
#endif

#ifdef __cplusplus
}
#endif

#endif /* MOTOR_CONFIG_H */
