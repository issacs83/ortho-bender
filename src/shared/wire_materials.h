/**
 * @file wire_materials.h
 * @brief Wire material definitions and mechanical properties
 *
 * IEC 62304 SW Class: B
 */

#ifndef ORTHO_BENDER_WIRE_MATERIALS_H
#define ORTHO_BENDER_WIRE_MATERIALS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────
 * Wire Material Types
 * ────────────────────────────────────────────── */

typedef enum {
    WIRE_MATERIAL_SS304         = 0,    /* Stainless Steel 304 */
    WIRE_MATERIAL_NITI          = 1,    /* Nickel-Titanium (superelastic) */
    WIRE_MATERIAL_BETA_TI       = 2,    /* Beta-Titanium (TMA) */
    WIRE_MATERIAL_CUNITI        = 3,    /* Copper-Nickel-Titanium */
    WIRE_MATERIAL_COUNT
} wire_material_t;

/* ──────────────────────────────────────────────
 * Wire Cross-Section Types
 * ────────────────────────────────────────────── */

typedef enum {
    WIRE_SECTION_ROUND          = 0,
    WIRE_SECTION_RECTANGULAR    = 1,
} wire_section_t;

/* ──────────────────────────────────────────────
 * Wire Material Properties
 * ────────────────────────────────────────────── */

typedef struct {
    wire_material_t material;
    const char*     name;

    /* Mechanical properties */
    float   youngs_modulus_gpa;     /* Young's modulus (GPa) */
    float   yield_strength_mpa;     /* 0.2% offset yield (MPa) */
    float   ultimate_strength_mpa;  /* Ultimate tensile strength (MPa) */
    float   elongation_pct;         /* Elongation at break (%) */

    /* Springback characteristics */
    float   springback_ratio;       /* Approximate springback K (theta_back/theta_bend) */
    uint8_t requires_heating;       /* 1 = needs temperature control */
    float   af_temperature_c;       /* Austenite finish temp (NiTi/CuNiTi only) */

    /* Bending limits */
    float   min_bend_radius_factor; /* Minimum bend radius = factor * wire_diameter */
    float   max_bend_angle_deg;     /* Maximum safe bend angle */
} wire_properties_t;

/* ──────────────────────────────────────────────
 * Material Database (default values)
 *
 * Note: Actual values may vary by lot/manufacturer.
 * These are conservative defaults for safety.
 * ────────────────────────────────────────────── */

static const wire_properties_t WIRE_MATERIAL_DB[WIRE_MATERIAL_COUNT] = {
    [WIRE_MATERIAL_SS304] = {
        .material               = WIRE_MATERIAL_SS304,
        .name                   = "Stainless Steel 304",
        .youngs_modulus_gpa     = 177.0f,
        .yield_strength_mpa     = 1100.0f,
        .ultimate_strength_mpa  = 1400.0f,
        .elongation_pct         = 2.0f,
        .springback_ratio       = 0.15f,
        .requires_heating       = 0,
        .af_temperature_c       = 0.0f,
        .min_bend_radius_factor = 2.0f,
        .max_bend_angle_deg     = 160.0f,
    },
    [WIRE_MATERIAL_NITI] = {
        .material               = WIRE_MATERIAL_NITI,
        .name                   = "Nickel-Titanium",
        .youngs_modulus_gpa     = 41.0f,
        .yield_strength_mpa     = 200.0f,
        .ultimate_strength_mpa  = 1240.0f,
        .elongation_pct         = 8.0f,
        .springback_ratio       = 0.60f,
        .requires_heating       = 1,
        .af_temperature_c       = 35.0f,
        .min_bend_radius_factor = 3.0f,
        .max_bend_angle_deg     = 120.0f,
    },
    [WIRE_MATERIAL_BETA_TI] = {
        .material               = WIRE_MATERIAL_BETA_TI,
        .name                   = "Beta-Titanium (TMA)",
        .youngs_modulus_gpa     = 69.0f,
        .yield_strength_mpa     = 690.0f,
        .ultimate_strength_mpa  = 1000.0f,
        .elongation_pct         = 5.0f,
        .springback_ratio       = 0.25f,
        .requires_heating       = 0,
        .af_temperature_c       = 0.0f,
        .min_bend_radius_factor = 2.5f,
        .max_bend_angle_deg     = 150.0f,
    },
    [WIRE_MATERIAL_CUNITI] = {
        .material               = WIRE_MATERIAL_CUNITI,
        .name                   = "Copper-Nickel-Titanium",
        .youngs_modulus_gpa     = 41.0f,
        .yield_strength_mpa     = 180.0f,
        .ultimate_strength_mpa  = 1100.0f,
        .elongation_pct         = 7.0f,
        .springback_ratio       = 0.55f,
        .requires_heating       = 1,
        .af_temperature_c       = 27.0f,
        .min_bend_radius_factor = 3.0f,
        .max_bend_angle_deg     = 120.0f,
    },
};

/**
 * @brief Get wire material properties by material ID
 * @return Pointer to properties, or NULL if invalid
 */
static inline const wire_properties_t* wire_get_properties(wire_material_t mat)
{
    if (mat >= WIRE_MATERIAL_COUNT) {
        return (const wire_properties_t*)0;
    }
    return &WIRE_MATERIAL_DB[mat];
}

#ifdef __cplusplus
}
#endif

#endif /* ORTHO_BENDER_WIRE_MATERIALS_H */
