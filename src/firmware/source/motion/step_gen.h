/**
 * @file step_gen.h
 * @brief STEP pulse generator -- GPT timer-based trapezoidal velocity profile
 * @author ortho-bender firmware team
 *
 * Generates STEP/DIR pulses for TMC260C-PA motor drivers using i.MX8MP M7 GPT
 * (General Purpose Timer) hardware.  Each axis uses an independent GPT channel:
 *   GPT1 -> FEED  (axis 0)
 *   GPT2 -> BEND  (axis 1)
 *   GPT3 -> ROTATE (axis 2, Phase 2)
 *   GPT4 -> LIFT   (axis 3, Phase 2)
 *
 * Trapezoidal velocity profile:
 *   Acceleration (constant accel)  -> Cruise (constant velocity) -> Deceleration
 *
 * The ISR toggles the STEP GPIO pin and updates the step counter.  The profile
 * state machine runs inside the ISR to recalculate the timer period for each
 * step, implementing real-time velocity profiling.
 *
 * All parameters are in microstep units.  The caller is responsible for
 * unit conversion (mm -> microsteps, deg -> microsteps).
 *
 * Memory: ~64 bytes per axis (static allocation)
 * No dynamic memory allocation.  ISR-safe (no blocking calls).
 *
 * IEC 62304 SW Class: B (safety-critical motion control)
 */

#ifndef STEP_GEN_H
#define STEP_GEN_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ======================================================================
 * Configuration
 * ====================================================================== */

/** Maximum number of step generator channels (one per axis) */
#define STEP_GEN_MAX_AXES       4U

/** Minimum step period in timer ticks (prevents overrun at very high speeds) */
#define STEP_GEN_MIN_PERIOD_TICKS   25U  /* 1 us at 25 MHz GPT clock */

/* ======================================================================
 * Profile state machine
 * ====================================================================== */

/** Step generator profile phase */
typedef enum {
    STEP_PHASE_IDLE     = 0,    /**< No motion */
    STEP_PHASE_ACCEL    = 1,    /**< Accelerating */
    STEP_PHASE_CRUISE   = 2,    /**< Constant velocity */
    STEP_PHASE_DECEL    = 3,    /**< Decelerating */
} step_phase_t;

/** Per-axis step generator state (volatile -- modified in ISR) */
typedef struct {
    /* Position tracking */
    volatile int32_t    position;       /**< Current position (signed microsteps) */
    volatile int32_t    target;         /**< Target position (signed microsteps) */
    volatile int32_t    steps_remaining;/**< Absolute steps remaining */

    /* Velocity profile */
    volatile uint32_t   current_period; /**< Current GPT period (timer ticks) */
    uint32_t            min_period;     /**< Min period = max velocity (ticks) */
    uint32_t            accel_inc;      /**< Acceleration: period decrement per step */
    uint32_t            decel_inc;      /**< Deceleration: period increment per step */
    uint32_t            start_period;   /**< Initial period at start of move */

    /* Profile state machine */
    volatile step_phase_t phase;        /**< Current profile phase */
    volatile uint32_t   accel_steps;    /**< Steps spent accelerating */
    volatile uint32_t   decel_start;    /**< Step count at which decel begins */
    volatile bool       direction;      /**< true = forward, false = reverse */

    /* Completion flag */
    volatile bool       complete;       /**< Move completed flag */
    volatile bool       active;         /**< Timer is running */
} step_gen_state_t;

/* ======================================================================
 * Public API
 * ====================================================================== */

/**
 * @brief Initialize step generator hardware (GPT timers + STEP/DIR GPIOs)
 * @param axis_count Number of axes to initialize (2 for Phase 1, 4 for Phase 2)
 * @return true on success
 *
 * Configures GPT timers in one-shot mode with ISR for step pulse generation.
 * Initializes STEP and DIR GPIO pins as outputs.
 */
bool step_gen_init(uint8_t axis_count);

/**
 * @brief Start a trapezoidal move on a single axis
 * @param axis      Axis index (0=FEED, 1=BEND, ...)
 * @param steps     Signed step count (positive=forward, negative=reverse)
 * @param max_freq  Maximum step frequency in Hz (cruise velocity)
 * @param accel     Acceleration in steps/s^2
 * @return true if move started, false if axis busy or invalid
 *
 * The function computes the trapezoidal profile and starts the GPT timer.
 * It returns immediately; use step_gen_is_complete() to poll for completion.
 *
 * Example: 3200 steps at 16000 Hz max, 80000 steps/s^2 accel
 *   -> accelerates ~0.2s, cruises, decelerates ~0.2s
 */
bool step_gen_move(uint8_t axis, int32_t steps, uint32_t max_freq, uint32_t accel);

/**
 * @brief Check if a move is complete on a given axis
 * @param axis  Axis index
 * @return true if the move has finished or no move is in progress
 */
bool step_gen_is_complete(uint8_t axis);

/**
 * @brief Immediately stop motion on a given axis (no deceleration)
 * @param axis  Axis index
 *
 * Stops the GPT timer and clears the step counter.  The position counter
 * retains the last known position.
 */
void step_gen_stop(uint8_t axis);

/**
 * @brief Stop all axes immediately
 */
void step_gen_stop_all(void);

/**
 * @brief Get current position of an axis
 * @param axis  Axis index
 * @return Current position in signed microsteps
 */
int32_t step_gen_get_position(uint8_t axis);

/**
 * @brief Set current position without moving (e.g., after homing)
 * @param axis      Axis index
 * @param position  New position value in microsteps
 */
void step_gen_set_position(uint8_t axis, int32_t position);

/**
 * @brief Start continuous velocity mode (for jogging)
 * @param axis      Axis index
 * @param freq      Step frequency in Hz (signed: positive=fwd, negative=rev)
 * @param accel     Acceleration in steps/s^2
 * @return true if started successfully
 *
 * Runs indefinitely until step_gen_stop() is called.
 */
bool step_gen_velocity_mode(uint8_t axis, int32_t freq, uint32_t accel);

/**
 * @brief GPT ISR handler for a specific axis
 * @param axis  Axis index (called from GPTn_IRQHandler)
 *
 * Toggles STEP GPIO, updates position counter, advances velocity profile.
 * Must execute in < 1 us to support step rates up to 250 kHz.
 *
 * This function is called from the GPT interrupt handler and must NOT be
 * called from task context.
 */
void step_gen_isr(uint8_t axis);

#ifdef __cplusplus
}
#endif

#endif /* STEP_GEN_H */
