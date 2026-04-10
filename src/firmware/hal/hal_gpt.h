/**
 * @file hal_gpt.h
 * @brief GPT (General Purpose Timer) hardware abstraction layer
 * @note Platform-specific implementation provided per board (board.c).
 *       Used by step_gen.c for STEP pulse generation via output compare ISR.
 *
 * IEC 62304 SW Class: B (safety-critical motion control)
 */

#ifndef HAL_GPT_H
#define HAL_GPT_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** GPT channel identifier (one per axis) */
typedef enum {
    HAL_GPT_CH0 = 0,   /**< GPT1 -> FEED axis  */
    HAL_GPT_CH1,        /**< GPT2 -> BEND axis  */
    HAL_GPT_CH2,        /**< GPT3 -> ROTATE axis (Phase 2) */
    HAL_GPT_CH3,        /**< GPT4 -> LIFT axis   (Phase 2) */
    HAL_GPT_CH_COUNT
} hal_gpt_ch_t;

/**
 * @brief Initialize a GPT channel for output compare interrupt operation
 * @param ch        Channel identifier
 * @param clock_hz  Desired timer clock frequency (after prescaler)
 * @return true on success
 *
 * Configures the GPT peripheral with the specified clock, enables the
 * output compare 1 interrupt, and registers the NVIC vector.
 * The timer is left disabled (stopped) after init.
 */
bool hal_gpt_init(hal_gpt_ch_t ch, uint32_t clock_hz);

/**
 * @brief Start a GPT channel with the given compare period
 * @param ch            Channel identifier
 * @param period_ticks  Output compare value (timer ticks between interrupts)
 *
 * Loads OCR1, resets counter, and enables the timer.
 */
void hal_gpt_start(hal_gpt_ch_t ch, uint32_t period_ticks);

/**
 * @brief Stop a GPT channel immediately
 * @param ch  Channel identifier
 */
void hal_gpt_stop(hal_gpt_ch_t ch);

/**
 * @brief Update output compare period on the fly (ISR-safe)
 * @param ch            Channel identifier
 * @param period_ticks  New output compare value
 *
 * Writes OCR1 without stopping the timer.  The new period takes effect
 * at the next compare event.
 */
void hal_gpt_set_period(hal_gpt_ch_t ch, uint32_t period_ticks);

#ifdef __cplusplus
}
#endif

#endif /* HAL_GPT_H */
