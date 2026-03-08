/**
 * @file wire_materials.c
 * @brief Wire material database and property lookup
 *
 * IEC 62304 SW Class: B
 */

#include "wire_materials.h"
#include <stddef.h>

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

const wire_properties_t* wire_get_properties(wire_material_t mat)
{
    if (mat >= WIRE_MATERIAL_COUNT) {
        return NULL;
    }
    return &WIRE_MATERIAL_DB[mat];
}
