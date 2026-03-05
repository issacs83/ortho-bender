/**
 * @file machine_config.h
 * @brief Machine geometry constants and axis configuration
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
 * Feed Axis (L) Configuration
 * ────────────────────────────────────────────── */

#define FEED_STEPS_PER_MM           200.0f      /* Stepper steps per mm */
#define FEED_MICROSTEP              16U         /* Microstepping divisor */
#define FEED_MAX_SPEED_MM_S         50.0f       /* Maximum speed (mm/s) */
#define FEED_MAX_ACCEL_MM_S2        200.0f      /* Maximum acceleration */
#define FEED_SOFT_LIMIT_MIN_MM      0.0f        /* Software limit min */
#define FEED_SOFT_LIMIT_MAX_MM      300.0f      /* Software limit max */

/* ──────────────────────────────────────────────
 * Rotate Axis (beta) Configuration
 * ────────────────────────────────────────────── */

#define ROTATE_STEPS_PER_DEG        (200.0f * 16.0f / 360.0f)  /* With 16:1 gear */
#define ROTATE_MICROSTEP            16U
#define ROTATE_MAX_SPEED_DEG_S      180.0f      /* Maximum speed (deg/s) */
#define ROTATE_MAX_ACCEL_DEG_S2     720.0f      /* Maximum acceleration */

/* ──────────────────────────────────────────────
 * Bend Axis (theta) Configuration
 * ────────────────────────────────────────────── */

#define BEND_STEPS_PER_DEG          100.0f      /* Servo encoder counts per deg */
#define BEND_MAX_SPEED_DEG_S        90.0f       /* Maximum speed (deg/s) */
#define BEND_MAX_ACCEL_DEG_S2       360.0f      /* Maximum acceleration */
#define BEND_SOFT_LIMIT_MIN_DEG     0.0f
#define BEND_SOFT_LIMIT_MAX_DEG     180.0f
#define BEND_FORCE_LIMIT_N          100.0f      /* Maximum bending force */

/* ──────────────────────────────────────────────
 * Safety Limits
 * ────────────────────────────────────────────── */

#define SAFETY_WATCHDOG_TIMEOUT_MS  200U        /* Watchdog timeout */
#define SAFETY_HEARTBEAT_PERIOD_MS  100U        /* Heartbeat interval to A53 */
#define SAFETY_FORCE_LIMIT_N        120.0f      /* Hard force limit */
#define SAFETY_TEMP_MAX_CELSIUS     300.0f      /* Maximum heater temperature */
#define SAFETY_TEMP_NITI_AF_C       70.0f       /* NiTi austenite finish temp (default) */

/* ──────────────────────────────────────────────
 * Control Loop Timing
 * ────────────────────────────────────────────── */

#define MOTION_LOOP_PERIOD_US       1000U       /* 1 kHz motion control loop */
#define SENSOR_SAMPLE_PERIOD_US     1000U       /* 1 kHz sensor sampling */
#define SAFETY_CHECK_PERIOD_US      100U        /* 10 kHz safety check */
#define STATUS_REPORT_PERIOD_MS     10U         /* 100 Hz status to A53 */

/* ──────────────────────────────────────────────
 * PID Defaults
 * ────────────────────────────────────────────── */

typedef struct {
    float kp;
    float ki;
    float kd;
    float max_output;
    float integral_limit;
} pid_defaults_t;

#define PID_FEED_DEFAULTS       { 2.0f, 0.1f, 0.05f, 100.0f, 50.0f }
#define PID_ROTATE_DEFAULTS     { 3.0f, 0.2f, 0.1f,  100.0f, 50.0f }
#define PID_BEND_DEFAULTS       { 5.0f, 0.5f, 0.2f,  100.0f, 50.0f }

#ifdef __cplusplus
}
#endif

#endif /* ORTHO_BENDER_MACHINE_CONFIG_H */
