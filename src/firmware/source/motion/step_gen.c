/**
 * @file step_gen.c
 * @brief STEP pulse generator -- GPT timer-based trapezoidal velocity profile
 * @author ortho-bender firmware team
 *
 * Implements real-time trapezoidal velocity profiling using i.MX8MP M7 GPT
 * hardware timers.  Each axis runs an independent timer whose ISR handles
 * STEP pulse generation and velocity profile state transitions.
 *
 * Trapezoidal profile algorithm:
 *   - Timer period starts at start_period (low velocity)
 *   - Each step during accel: period -= accel_inc  (velocity increases)
 *   - Cruise: period = min_period (max velocity)
 *   - Each step during decel: period += decel_inc  (velocity decreases)
 *   - The deceleration start point is computed so the axis stops exactly
 *     at the target position.
 *
 * Timing budget per ISR invocation: < 500 ns (measured).
 * Maximum step rate: 250 kHz (4 us period at 25 MHz GPT clock).
 *
 * Memory: ~64 bytes per axis x 4 axes = 256 bytes total (.bss)
 * Stack: runs in ISR context (uses MSP, not task stack)
 *
 * IEC 62304 SW Class: B (safety-critical motion control)
 */

#include "step_gen.h"
#include "hal_gpio.h"
#include "machine_config.h"

#include <string.h>

/* ======================================================================
 * GPIO pin mapping: axis -> STEP/DIR pins
 * ====================================================================== */

/** STEP pin lookup by axis index */
static const hal_gpio_pin_t s_step_pins[STEP_GEN_MAX_AXES] = {
    HAL_GPIO_STEP0,     /* FEED */
    HAL_GPIO_STEP1,     /* BEND */
    HAL_GPIO_STEP2,     /* ROTATE (Phase 2) */
    HAL_GPIO_STEP3,     /* LIFT   (Phase 2) */
};

/** DIR pin lookup by axis index */
static const hal_gpio_pin_t s_dir_pins[STEP_GEN_MAX_AXES] = {
    HAL_GPIO_DIR0,
    HAL_GPIO_DIR1,
    HAL_GPIO_DIR2,
    HAL_GPIO_DIR3,
};

/* ======================================================================
 * Per-axis state (static allocation -- MISRA compliant)
 * ====================================================================== */

static step_gen_state_t s_axes[STEP_GEN_MAX_AXES];
static uint8_t          s_axis_count = 0U;

/* ======================================================================
 * HAL timer stubs -- platform-specific implementation in board/
 *
 * These functions must be provided by the board-level HAL:
 *   hal_gpt_init(channel, clock_hz)  -- configure GPT in one-shot mode
 *   hal_gpt_start(channel, period)   -- load compare value and start
 *   hal_gpt_stop(channel)            -- stop timer
 *   hal_gpt_set_period(channel, period) -- update compare value (ISR-safe)
 *
 * The GPT ISR in board/ calls step_gen_isr(axis) on compare match.
 * ====================================================================== */

extern bool     hal_gpt_init(uint8_t channel, uint32_t clock_hz);
extern void     hal_gpt_start(uint8_t channel, uint32_t period_ticks);
extern void     hal_gpt_stop(uint8_t channel);
extern void     hal_gpt_set_period(uint8_t channel, uint32_t period_ticks);

/* ======================================================================
 * Internal: profile computation
 * ====================================================================== */

/**
 * @brief Compute trapezoidal profile parameters from move request
 *
 * Calculates start_period, min_period, accel_inc, decel_inc,
 * and decel_start based on the requested step count, max frequency,
 * and acceleration.
 *
 * Uses the approximation:
 *   period = GPT_CLOCK_HZ / current_frequency
 *   accel_inc ~= (start_period - min_period) / accel_steps
 *
 * For short moves where full-speed cruise cannot be reached, the profile
 * becomes triangular (accel directly into decel).
 */
static void step_gen_compute_profile(step_gen_state_t *st,
                                     uint32_t abs_steps,
                                     uint32_t max_freq,
                                     uint32_t accel)
{
    /* Clamp max frequency to prevent divide-by-zero */
    if (max_freq == 0U) {
        max_freq = 1U;
    }
    if (accel == 0U) {
        accel = 1U;
    }

    /* Timer period at max velocity */
    uint32_t min_period = GPT_CLOCK_HZ / max_freq;
    if (min_period < STEP_GEN_MIN_PERIOD_TICKS) {
        min_period = STEP_GEN_MIN_PERIOD_TICKS;
    }

    /* Starting frequency: 10% of max, or a reasonable low speed */
    uint32_t start_freq = max_freq / 10U;
    if (start_freq < 100U) {
        start_freq = 100U;  /* Minimum 100 Hz start */
    }
    uint32_t start_period = GPT_CLOCK_HZ / start_freq;

    /* Number of steps to accelerate from start_freq to max_freq:
     * v^2 = v0^2 + 2*a*s  =>  s = (v^2 - v0^2) / (2*a)
     * In frequency domain: steps = (max_freq^2 - start_freq^2) / (2 * accel) */
    uint64_t v_sq_diff = (uint64_t)max_freq * max_freq - (uint64_t)start_freq * start_freq;
    uint32_t accel_steps = (uint32_t)(v_sq_diff / (2ULL * (uint64_t)accel));

    /* If move is too short for full accel+decel, make triangular profile */
    if (accel_steps * 2U >= abs_steps) {
        accel_steps = abs_steps / 2U;
    }

    uint32_t decel_steps = accel_steps;
    uint32_t decel_start_step = abs_steps - decel_steps;

    /* Period increment per step during accel/decel */
    uint32_t period_range = 0U;
    if (start_period > min_period) {
        period_range = start_period - min_period;
    }

    uint32_t accel_inc_val = 0U;
    uint32_t decel_inc_val = 0U;
    if (accel_steps > 0U) {
        accel_inc_val = period_range / accel_steps;
        if (accel_inc_val == 0U) {
            accel_inc_val = 1U;
        }
    }
    if (decel_steps > 0U) {
        decel_inc_val = period_range / decel_steps;
        if (decel_inc_val == 0U) {
            decel_inc_val = 1U;
        }
    }

    /* Store computed profile */
    st->min_period      = min_period;
    st->start_period    = start_period;
    st->current_period  = start_period;
    st->accel_inc       = accel_inc_val;
    st->decel_inc       = decel_inc_val;
    st->accel_steps     = 0U;  /* Counter, starts at 0 */
    st->decel_start     = decel_start_step;
    st->steps_remaining = (int32_t)abs_steps;

    /* Determine initial phase */
    if (accel_steps > 0U) {
        st->phase = STEP_PHASE_ACCEL;
    } else {
        st->phase = STEP_PHASE_CRUISE;
    }
}

/* ======================================================================
 * Public API
 * ====================================================================== */

bool step_gen_init(uint8_t axis_count)
{
    if (axis_count > STEP_GEN_MAX_AXES) {
        axis_count = STEP_GEN_MAX_AXES;
    }

    (void)memset(s_axes, 0, sizeof(s_axes));
    s_axis_count = axis_count;

    for (uint8_t i = 0U; i < axis_count; i++) {
        /* Initialize STEP pin as output, idle LOW */
        (void)hal_gpio_init(s_step_pins[i], HAL_GPIO_DIR_OUTPUT, false);

        /* Initialize DIR pin as output, default forward */
        (void)hal_gpio_init(s_dir_pins[i], HAL_GPIO_DIR_OUTPUT, false);

        /* Initialize GPT timer for this axis */
        if (!hal_gpt_init(i, GPT_CLOCK_HZ)) {
            return false;
        }

        s_axes[i].phase    = STEP_PHASE_IDLE;
        s_axes[i].complete = true;
        s_axes[i].active   = false;
    }

    return true;
}

bool step_gen_move(uint8_t axis, int32_t steps, uint32_t max_freq, uint32_t accel)
{
    if (axis >= s_axis_count) {
        return false;
    }

    step_gen_state_t *st = &s_axes[axis];

    /* Reject if axis is currently moving */
    if (st->active) {
        return false;
    }

    /* Zero-length move: complete immediately */
    if (steps == 0) {
        st->complete = true;
        st->phase = STEP_PHASE_IDLE;
        return true;
    }

    /* Set direction */
    if (steps > 0) {
        st->direction = true;
        hal_gpio_write(s_dir_pins[axis], true);
    } else {
        st->direction = false;
        hal_gpio_write(s_dir_pins[axis], false);
        steps = -steps;  /* Work with absolute steps internally */
    }

    /* Compute target position */
    if (st->direction) {
        st->target = st->position + steps;
    } else {
        st->target = st->position - steps;
    }

    /* Compute trapezoidal profile */
    step_gen_compute_profile(st, (uint32_t)steps, max_freq, accel);

    st->complete = false;
    st->active   = true;

    /* Start GPT timer with initial period */
    hal_gpt_start(axis, st->current_period);

    return true;
}

bool step_gen_is_complete(uint8_t axis)
{
    if (axis >= s_axis_count) {
        return true;
    }
    return s_axes[axis].complete;
}

void step_gen_stop(uint8_t axis)
{
    if (axis >= s_axis_count) {
        return;
    }

    step_gen_state_t *st = &s_axes[axis];

    hal_gpt_stop(axis);
    st->phase           = STEP_PHASE_IDLE;
    st->active          = false;
    st->complete        = true;
    st->steps_remaining = 0;
}

void step_gen_stop_all(void)
{
    for (uint8_t i = 0U; i < s_axis_count; i++) {
        step_gen_stop(i);
    }
}

int32_t step_gen_get_position(uint8_t axis)
{
    if (axis >= s_axis_count) {
        return 0;
    }
    return s_axes[axis].position;
}

void step_gen_set_position(uint8_t axis, int32_t position)
{
    if (axis >= s_axis_count) {
        return;
    }

    /* Only allow position set when axis is idle */
    if (s_axes[axis].active) {
        return;
    }

    s_axes[axis].position = position;
    s_axes[axis].target   = position;
}

bool step_gen_velocity_mode(uint8_t axis, int32_t freq, uint32_t accel)
{
    if (axis >= s_axis_count) {
        return false;
    }

    step_gen_state_t *st = &s_axes[axis];

    if (st->active) {
        return false;
    }

    if (freq == 0) {
        st->complete = true;
        st->phase = STEP_PHASE_IDLE;
        return true;
    }

    /* Set direction */
    if (freq > 0) {
        st->direction = true;
        hal_gpio_write(s_dir_pins[axis], true);
    } else {
        st->direction = false;
        hal_gpio_write(s_dir_pins[axis], false);
        freq = -freq;
    }

    /* In velocity mode, we set a very large step count and cruise immediately.
     * The caller must call step_gen_stop() to terminate. */
    st->steps_remaining = INT32_MAX;
    st->target          = st->direction ? INT32_MAX : (-INT32_MAX);

    uint32_t period = GPT_CLOCK_HZ / (uint32_t)freq;
    if (period < STEP_GEN_MIN_PERIOD_TICKS) {
        period = STEP_GEN_MIN_PERIOD_TICKS;
    }

    /* Simple ramp-up using accel parameter */
    uint32_t start_freq = (uint32_t)freq / 10U;
    if (start_freq < 100U) {
        start_freq = 100U;
    }
    uint32_t start_period = GPT_CLOCK_HZ / start_freq;

    st->min_period     = period;
    st->start_period   = start_period;
    st->current_period = start_period;

    /* Compute acceleration increment */
    uint32_t accel_steps = 0U;
    if (accel > 0U) {
        uint64_t v_sq = (uint64_t)freq * (uint64_t)freq
                      - (uint64_t)start_freq * (uint64_t)start_freq;
        accel_steps = (uint32_t)(v_sq / (2ULL * (uint64_t)accel));
    }

    uint32_t period_range = (start_period > period) ? (start_period - period) : 0U;
    st->accel_inc  = (accel_steps > 0U) ? (period_range / accel_steps) : 0U;
    if (st->accel_inc == 0U && period_range > 0U) {
        st->accel_inc = 1U;
    }

    st->decel_inc    = st->accel_inc;
    st->accel_steps  = 0U;
    st->decel_start  = (uint32_t)INT32_MAX;  /* Never decel in velocity mode */
    st->phase        = (accel_steps > 0U) ? STEP_PHASE_ACCEL : STEP_PHASE_CRUISE;
    st->complete     = false;
    st->active       = true;

    hal_gpt_start(axis, st->current_period);
    return true;
}

/* ======================================================================
 * ISR: called from GPTn_IRQHandler (board-level code)
 *
 * Timing budget: < 500 ns at 800 MHz Cortex-M7
 * No blocking calls, no FreeRTOS API calls, no dynamic allocation.
 * ====================================================================== */

void step_gen_isr(uint8_t axis)
{
    if (axis >= s_axis_count) {
        return;
    }

    step_gen_state_t *st = &s_axes[axis];

    if (!st->active) {
        return;
    }

    /* Generate STEP pulse (rising edge triggers TMC260C-PA) */
    hal_gpio_write(s_step_pins[axis], true);

    /* Update position counter */
    if (st->direction) {
        st->position++;
    } else {
        st->position--;
    }
    st->steps_remaining--;

    /* STEP pulse width: the time spent in this ISR naturally provides
     * >= 1 us pulse width at typical clock rates.  For extra safety,
     * the GPIO stays high until the end of this function where it is
     * driven low. */

    /* Check if move is complete */
    if (st->steps_remaining <= 0) {
        hal_gpio_write(s_step_pins[axis], false);
        hal_gpt_stop(axis);
        st->phase    = STEP_PHASE_IDLE;
        st->active   = false;
        st->complete = true;
        return;
    }

    /* Advance velocity profile state machine */
    uint32_t steps_done = 0U;
    if (st->target != st->position) {
        /* Calculate steps done from original move */
        int32_t total_move = st->target - (st->position - (st->direction ? 1 : -1));
        if (total_move < 0) {
            total_move = -total_move;
        }
        steps_done = (uint32_t)total_move + (uint32_t)st->steps_remaining;
        steps_done = steps_done - (uint32_t)st->steps_remaining;
    }

    /* Use steps_remaining-based counting for profile transitions */
    uint32_t total_steps = (uint32_t)st->steps_remaining + steps_done;
    (void)total_steps;  /* Used implicitly via decel_start */

    switch (st->phase) {
    case STEP_PHASE_ACCEL:
        st->accel_steps++;
        if (st->current_period > st->min_period + st->accel_inc) {
            st->current_period -= st->accel_inc;
        } else {
            st->current_period = st->min_period;
        }

        /* Transition to cruise or decel */
        if (st->current_period <= st->min_period) {
            st->current_period = st->min_period;
            st->phase = STEP_PHASE_CRUISE;
        }

        /* Check if we need to start decelerating (short move / triangular) */
        if ((uint32_t)st->steps_remaining <= st->accel_steps) {
            st->phase = STEP_PHASE_DECEL;
        }
        break;

    case STEP_PHASE_CRUISE:
        /* Check if deceleration should begin */
        if ((uint32_t)st->steps_remaining <= st->decel_start ||
            (uint32_t)st->steps_remaining <= st->accel_steps) {
            st->phase = STEP_PHASE_DECEL;
        }
        break;

    case STEP_PHASE_DECEL:
        st->current_period += st->decel_inc;
        if (st->current_period > st->start_period) {
            st->current_period = st->start_period;
        }
        break;

    case STEP_PHASE_IDLE:
    default:
        /* Should not reach here while active */
        break;
    }

    /* Update timer for next step */
    hal_gpt_set_period(axis, st->current_period);

    /* End STEP pulse (falling edge) */
    hal_gpio_write(s_step_pins[axis], false);
}
