/**
 * @file test_wire_materials.cpp
 * @brief Unit tests for wire material database and property lookup
 *
 * IEC 62304 SW Class: B
 */

#include <gtest/gtest.h>

extern "C" {
#include "wire_materials.h"
}

// ── wire_get_properties: valid materials ──

TEST(WireMaterials, SS304PropertiesValid)
{
    const wire_properties_t *p = wire_get_properties(WIRE_MATERIAL_SS304);
    ASSERT_NE(p, nullptr);
    EXPECT_EQ(p->material, WIRE_MATERIAL_SS304);
    EXPECT_FLOAT_EQ(p->youngs_modulus_gpa, 177.0f);
    EXPECT_FLOAT_EQ(p->springback_ratio, 0.15f);
    EXPECT_EQ(p->requires_heating, 0);
}

TEST(WireMaterials, NiTiPropertiesValid)
{
    const wire_properties_t *p = wire_get_properties(WIRE_MATERIAL_NITI);
    ASSERT_NE(p, nullptr);
    EXPECT_EQ(p->material, WIRE_MATERIAL_NITI);
    EXPECT_FLOAT_EQ(p->springback_ratio, 0.60f);
    EXPECT_EQ(p->requires_heating, 1);
    EXPECT_GT(p->af_temperature_c, 0.0f);
}

TEST(WireMaterials, BetaTiPropertiesValid)
{
    const wire_properties_t *p = wire_get_properties(WIRE_MATERIAL_BETA_TI);
    ASSERT_NE(p, nullptr);
    EXPECT_EQ(p->material, WIRE_MATERIAL_BETA_TI);
    EXPECT_FLOAT_EQ(p->springback_ratio, 0.25f);
    EXPECT_EQ(p->requires_heating, 0);
}

TEST(WireMaterials, CuNiTiPropertiesValid)
{
    const wire_properties_t *p = wire_get_properties(WIRE_MATERIAL_CUNITI);
    ASSERT_NE(p, nullptr);
    EXPECT_EQ(p->material, WIRE_MATERIAL_CUNITI);
    EXPECT_FLOAT_EQ(p->springback_ratio, 0.55f);
    EXPECT_EQ(p->requires_heating, 1);
}

// ── wire_get_properties: boundary conditions ──

TEST(WireMaterials, InvalidMaterialReturnsNull)
{
    EXPECT_EQ(wire_get_properties(WIRE_MATERIAL_COUNT), nullptr);
    EXPECT_EQ(wire_get_properties(static_cast<wire_material_t>(99)), nullptr);
}

TEST(WireMaterials, FirstMaterialValid)
{
    const wire_properties_t *p = wire_get_properties(static_cast<wire_material_t>(0));
    ASSERT_NE(p, nullptr);
    EXPECT_EQ(p->material, WIRE_MATERIAL_SS304);
}

TEST(WireMaterials, LastMaterialValid)
{
    const wire_properties_t *p = wire_get_properties(
        static_cast<wire_material_t>(WIRE_MATERIAL_COUNT - 1));
    ASSERT_NE(p, nullptr);
}

// ── Physical property sanity checks ──

TEST(WireMaterials, AllMaterialsHavePositiveModulus)
{
    for (int i = 0; i < WIRE_MATERIAL_COUNT; i++) {
        const wire_properties_t *p = wire_get_properties(static_cast<wire_material_t>(i));
        ASSERT_NE(p, nullptr);
        EXPECT_GT(p->youngs_modulus_gpa, 0.0f) << "Material " << i;
        EXPECT_GT(p->yield_strength_mpa, 0.0f) << "Material " << i;
        EXPECT_GT(p->max_bend_angle_deg, 0.0f) << "Material " << i;
        EXPECT_GT(p->min_bend_radius_factor, 0.0f) << "Material " << i;
    }
}

TEST(WireMaterials, SpringbackRatioInValidRange)
{
    for (int i = 0; i < WIRE_MATERIAL_COUNT; i++) {
        const wire_properties_t *p = wire_get_properties(static_cast<wire_material_t>(i));
        ASSERT_NE(p, nullptr);
        EXPECT_GE(p->springback_ratio, 0.0f) << "Material " << i;
        EXPECT_LT(p->springback_ratio, 1.0f) << "Material " << i;
    }
}

TEST(WireMaterials, HeatingMaterialsHaveAfTemp)
{
    for (int i = 0; i < WIRE_MATERIAL_COUNT; i++) {
        const wire_properties_t *p = wire_get_properties(static_cast<wire_material_t>(i));
        ASSERT_NE(p, nullptr);
        if (p->requires_heating) {
            EXPECT_GT(p->af_temperature_c, 0.0f)
                << "Material " << i << " requires heating but has no Af temp";
        }
    }
}

TEST(WireMaterials, AllMaterialsHaveNames)
{
    for (int i = 0; i < WIRE_MATERIAL_COUNT; i++) {
        const wire_properties_t *p = wire_get_properties(static_cast<wire_material_t>(i));
        ASSERT_NE(p, nullptr);
        EXPECT_NE(p->name, nullptr) << "Material " << i;
        EXPECT_GT(strlen(p->name), 0u) << "Material " << i;
    }
}
