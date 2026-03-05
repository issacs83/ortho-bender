/**
 * @file pid_controller.h
 * @brief PID controller with anti-windup and feed-forward
 *
 * IEC 62304 SW Class: B
 */

#ifndef PID_CONTROLLER_H
#define PID_CONTROLLER_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    /* Gains */
    float kp;
    float ki;
    float kd;

    /* Limits */
    float max_output;
    float integral_limit;

    /* State (internal) */
    float integral;
    float prev_error;
    float output;
} pid_state_t;

/**
 * @brief Initialize PID controller
 */
void pid_init(pid_state_t *pid, float kp, float ki, float kd,
              float max_output, float integral_limit);

/**
 * @brief Reset PID integrator and state
 */
void pid_reset(pid_state_t *pid);

/**
 * @brief Compute PID output
 * @param pid PID state
 * @param setpoint Target value
 * @param measurement Current value
 * @param dt Time step in seconds
 * @return Control output (clamped to +/- max_output)
 */
float pid_compute(pid_state_t *pid, float setpoint, float measurement, float dt);

#ifdef __cplusplus
}
#endif

#endif /* PID_CONTROLLER_H */
