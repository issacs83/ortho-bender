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

/**
 * @brief Get wire material properties by material ID
 * @return Pointer to properties, or NULL if invalid
 */
const wire_properties_t* wire_get_properties(wire_material_t mat);

#ifdef __cplusplus
}
#endif

#endif /* ORTHO_BENDER_WIRE_MATERIALS_H */
