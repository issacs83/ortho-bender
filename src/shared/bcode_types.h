/**
 * @file bcode_types.h
 * @brief B-code data types for wire bending operations
 * @note B-code = (Feed L, Rotate beta, Bend theta) machine instructions
 *
 * IEC 62304 SW Class: B
 */

#ifndef ORTHO_BENDER_BCODE_TYPES_H
#define ORTHO_BENDER_BCODE_TYPES_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────
 * B-code Constants
 * ────────────────────────────────────────────── */

#define BCODE_MAX_STEPS             128     /* Max steps per wire */
#define BCODE_MIN_FEED_MM           0.5f    /* Minimum feed length */
#define BCODE_MAX_FEED_MM           200.0f  /* Maximum feed length */
#define BCODE_MIN_BEND_DEG          0.5f    /* Minimum bend angle */
#define BCODE_MAX_BEND_DEG          180.0f  /* Maximum bend angle */
#define BCODE_MAX_ROTATE_DEG        360.0f  /* Maximum rotation */

/* ──────────────────────────────────────────────
 * B-code Step
 * ────────────────────────────────────────────── */

/**
 * @brief Single B-code operation step
 *
 * Each step represents one atomic bending operation:
 * 1. Feed wire by L_mm millimeters
 * 2. Rotate wire by beta_deg degrees around its longitudinal axis
 * 3. Bend wire by theta_deg degrees in the bending plane
 */
typedef struct {
    float   L_mm;           /**< Feed length in millimeters */
    float   beta_deg;       /**< Rotation angle in degrees (-360..+360) */
    float   theta_deg;      /**< Bend angle in degrees (0..180) */
    float   theta_compensated_deg;  /**< Bend angle after springback compensation */
} bcode_step_full_t;

/* ──────────────────────────────────────────────
 * B-code Sequence
 * ────────────────────────────────────────────── */

/**
 * @brief Complete B-code sequence for one wire
 */
typedef struct {
    uint16_t            step_count;     /**< Number of valid steps */
    uint16_t            material_id;    /**< Wire material (wire_material_t) */
    float               wire_diameter_mm;
    float               total_wire_length_mm;   /**< Total wire length needed */
    bcode_step_full_t   steps[BCODE_MAX_STEPS];
} bcode_sequence_t;

/* ──────────────────────────────────────────────
 * B-code Validation Result
 * ────────────────────────────────────────────── */

typedef enum {
    BCODE_VALID             = 0,
    BCODE_ERR_TOO_MANY_STEPS,
    BCODE_ERR_FEED_OUT_OF_RANGE,
    BCODE_ERR_BEND_OUT_OF_RANGE,
    BCODE_ERR_TOTAL_LENGTH_EXCEEDED,
    BCODE_ERR_COLLISION_DETECTED,
} bcode_validation_t;

#ifdef __cplusplus
}
#endif

#endif /* ORTHO_BENDER_BCODE_TYPES_H */
