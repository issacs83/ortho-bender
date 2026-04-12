/**
 * @file machine_config.h
 * @brief Machine geometry constants and axis configuration
 * @note All axes use TMC260C-PA stepper drivers with STEP/DIR interface.
 *       M7 generates STEP pulses via GPT timers; TMC260C-PA handles current
 *       chopping and StallGuard2 diagnostics via SPI configuration.
 *
 * IEC 62304 SW Class: B
 */

#ifndef ORTHO_BENDER_MACHINE_CONFIG_H
#define ORTHO_BENDER_MACHINE_CONFIG_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────
 * Feed Axis (L) Configuration — TMC260C-PA #0
 * ────────────────────────────────────────────── */

#define FEED_STEPS_PER_MM           200.0f      /* Motor full steps per mm */
#define FEED_MICROSTEP              16U         /* Microstepping divisor */
#define FEED_USTEPS_PER_MM          (FEED_STEPS_PER_MM * FEED_MICROSTEP)
#define FEED_MAX_SPEED_MM_S         50.0f       /* Maximum speed (mm/s) */
#define FEED_MAX_ACCEL_MM_S2        200.0f      /* Maximum acceleration */
#define FEED_SOFT_LIMIT_MIN_MM      0.0f        /* Software limit min */
#define FEED_SOFT_LIMIT_MAX_MM      300.0f      /* Software limit max */
#define FEED_SG_THRESHOLD           7U          /* StallGuard2 threshold (from B2 legacy) */

/* ──────────────────────────────────────────────
 * Bend Axis (theta) Configuration — TMC260C-PA #1
 * ────────────────────────────────────────────── */

#define BEND_STEPS_PER_DEG          (200.0f / 360.0f)   /* Stepper: 200 steps/rev */
#define BEND_MICROSTEP              16U
#define BEND_USTEPS_PER_DEG         (BEND_STEPS_PER_DEG * BEND_MICROSTEP)
#define BEND_GEAR_RATIO             20.0f       /* Planetary gearbox ratio */
#define BEND_MAX_SPEED_DEG_S        90.0f       /* Maximum speed (deg/s) */
#define BEND_MAX_ACCEL_DEG_S2       360.0f      /* Maximum acceleration */
#define BEND_SOFT_LIMIT_MIN_DEG     0.0f
#define BEND_SOFT_LIMIT_MAX_DEG     180.0f
#define BEND_SG_THRESHOLD           10U         /* StallGuard2 threshold (from B2 legacy) */

/* ──────────────────────────────────────────────
 * Rotate Axis (beta) Configuration — TMC260C-PA #2 (Phase 2)
 * ────────────────────────────────────────────── */

#define ROTATE_STEPS_PER_DEG        (200.0f / 360.0f)
#define ROTATE_MICROSTEP            16U
#define ROTATE_USTEPS_PER_DEG       (ROTATE_STEPS_PER_DEG * ROTATE_MICROSTEP)
#define ROTATE_GEAR_RATIO           16.0f       /* Planetary gearbox ratio */
#define ROTATE_MAX_SPEED_DEG_S      180.0f      /* Maximum speed (deg/s) */
#define ROTATE_MAX_ACCEL_DEG_S2     720.0f      /* Maximum acceleration */
#define ROTATE_SG_THRESHOLD         8U

/* ──────────────────────────────────────────────
 * Lift Axis Configuration — TMC260C-PA #3 (Phase 2)
 * ────────────────────────────────────────────── */

#define LIFT_STEPS_PER_DEG          (200.0f / 360.0f)
#define LIFT_MICROSTEP              16U
#define LIFT_USTEPS_PER_DEG         (LIFT_STEPS_PER_DEG * LIFT_MICROSTEP)
#define LIFT_GEAR_RATIO             10.0f
#define LIFT_MAX_SPEED_DEG_S        90.0f
#define LIFT_MAX_ACCEL_DEG_S2       360.0f
#define LIFT_SG_THRESHOLD           8U

/* ──────────────────────────────────────────────
 * TMC260C-PA SPI Configuration
 * ────────────────────────────────────────────── */

#define TMC260C_SPI_CLOCK_HZ       2000000U    /* 2 MHz (TMC260C-PA safe max) */
#define TMC260C_SPI_MODE            3U          /* CPOL=1, CPHA=1 */
#define TMC260C_CS_SETUP_NS         100U        /* CS assert to SCLK delay */
#define TMC260C_AXIS_COUNT          2U          /* Phase 1: FEED + BEND */
/* #define TMC260C_AXIS_COUNT       4U */       /* Phase 2: + ROTATE + LIFT */

/** Number of TMC5160 chips (for tmc_poll_task and diagnostic reads) */
#define TMC5160_CHIP_COUNT          AXIS_MAX

/* TMC260C-PA default current settings (0-31 scale, SGCSCONF CS field) */
#define TMC260C_IHOLD_DEFAULT       8U          /* Hold current (not used directly by TMC260C) */
#define TMC260C_IRUN_DEFAULT        20U         /* Run current scale */

/* ──────────────────────────────────────────────
 * STEP Pulse Generation (GPT Timer)
 * ────────────────────────────────────────────── */

#define STEP_PULSE_WIDTH_US         2U          /* STEP pulse min width (TMC260C min: 1 us) */
#define GPT_CLOCK_HZ                25000000U   /* GPT clock (i.MX8MP M7 GPT default) */

/* ──────────────────────────────────────────────
 * Safety Limits
 * ────────────────────────────────────────────── */

#define SAFETY_WATCHDOG_TIMEOUT_MS  200U        /* Watchdog timeout */
#define SAFETY_HEARTBEAT_PERIOD_MS  100U        /* Heartbeat interval to A53 */
#define SAFETY_TEMP_MAX_CELSIUS     300.0f      /* Maximum heater temperature */
#define SAFETY_TEMP_NITI_AF_C       70.0f       /* NiTi austenite finish temp (default) */

/* ──────────────────────────────────────────────
 * Control Loop Timing (STEP/DIR architecture)
 * ────────────────────────────────────────────── */

#define MOTION_LOOP_PERIOD_US       10000U      /* 100 Hz trajectory sequence manager */
#define TMC_POLL_PERIOD_US          5000U       /* 200 Hz TMC260C status polling (SPI) */
#define SAFETY_CHECK_PERIOD_US      100U        /* 10 kHz safety check (GPIO only) */
#define STATUS_REPORT_PERIOD_MS     100U        /* 10 Hz status to A53 */

/* ──────────────────────────────────────────────
 * Homing Configuration
 * ────────────────────────────────────────────── */

#define HOMING_COARSE_SPEED_FACTOR  0.5f        /* 50% of max speed for StallGuard search */
#define HOMING_FINE_SPEED_FACTOR    0.1f        /* 10% of max speed for fine approach */
#define HOMING_BACKOFF_STEPS        200         /* Steps to retract after SG trigger */

#ifdef __cplusplus
}
#endif

#endif /* ORTHO_BENDER_MACHINE_CONFIG_H */
