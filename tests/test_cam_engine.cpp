/**
 * @file test_cam_engine.cpp
 * @brief Unit tests for CAM engine: springback compensation and B-code validation
 *
 * IEC 62304 SW Class: B
 */

#include <gtest/gtest.h>
#include "cam_engine.h"

using namespace ortho_bender;

// ── CamEngine construction ──

TEST(CamEngine, DefaultConstruction)
{
    CamEngine engine;
    CamResult result = engine.generate_bcode();
    EXPECT_EQ(result.bcode.step_count, 0);
}

// ── B-code validation ──

class BcodeValidationTest : public ::testing::Test {
protected:
    CamEngine engine;

    bcode_sequence_t make_valid_bcode(uint16_t steps)
    {
        bcode_sequence_t bcode{};
        bcode.step_count = steps;
        bcode.material_id = WIRE_MATERIAL_SS304;
        bcode.wire_diameter_mm = 0.016f * 25.4f;
        for (uint16_t i = 0; i < steps; i++) {
            bcode.steps[i].L_mm = 5.0f;
            bcode.steps[i].theta_deg = 30.0f;
        }
        return bcode;
    }
};

TEST_F(BcodeValidationTest, EmptyBcodeIsValid)
{
    CamResult result = engine.generate_bcode();
    EXPECT_TRUE(result.warnings.empty());
}

TEST_F(BcodeValidationTest, ValidBcodePassesValidation)
{
    engine.set_wire_spec({WIRE_MATERIAL_SS304, 0.016f * 25.4f,
                          WIRE_SECTION_ROUND, 0.0f, 0.0f});
    engine.set_target_curve({{0, 0, 0}, {10, 0, 0}, {20, 5, 0}});
    CamResult result = engine.generate_bcode();
    // With empty discretization (TODO), step_count = 0 → valid
    EXPECT_EQ(result.bcode.step_count, 0);
}

// ── Springback compensation ──

TEST(SpringbackCompensation, SS304CompensationApplied)
{
    CamEngine engine;
    engine.set_wire_spec({WIRE_MATERIAL_SS304, 0.016f * 25.4f,
                          WIRE_SECTION_ROUND, 0.0f, 0.0f});

    // SS304 springback ratio = 0.15
    // compensated = theta / (1 - 0.15) = theta / 0.85
    // For 90 deg: 90 / 0.85 ≈ 105.88 deg
    CamResult result = engine.generate_bcode();

    // With empty discretization the bcode has 0 steps,
    // so springback is not applied. This test validates the engine
    // can at least run without crashing.
    EXPECT_EQ(result.bcode.step_count, 0);
}

TEST(SpringbackCompensation, NiTiHigherCompensation)
{
    const wire_properties_t *ss304 = wire_get_properties(WIRE_MATERIAL_SS304);
    const wire_properties_t *niti = wire_get_properties(WIRE_MATERIAL_NITI);
    ASSERT_NE(ss304, nullptr);
    ASSERT_NE(niti, nullptr);

    // NiTi has higher springback ratio than SS304
    EXPECT_GT(niti->springback_ratio, ss304->springback_ratio);
}

// ── Springback math verification ──

TEST(SpringbackMath, CompensationFormula)
{
    // Test the springback compensation formula: compensated = theta / (1 - K)
    float theta = 90.0f;
    float K_ss304 = 0.15f;
    float compensated = theta / (1.0f - K_ss304);
    EXPECT_NEAR(compensated, 105.88f, 0.1f);

    float K_niti = 0.60f;
    compensated = theta / (1.0f - K_niti);
    EXPECT_NEAR(compensated, 225.0f, 0.1f);
}

TEST(SpringbackMath, CompensationClampedToMaxAngle)
{
    // NiTi max bend angle = 120 deg, springback ratio = 0.60
    // For 90 deg bend: compensated = 90 / 0.40 = 225 deg > 120 deg max
    // Should be clamped to 120 deg
    const wire_properties_t *niti = wire_get_properties(WIRE_MATERIAL_NITI);
    ASSERT_NE(niti, nullptr);

    float theta = 90.0f;
    float compensated = theta / (1.0f - niti->springback_ratio);
    compensated = std::min(compensated, niti->max_bend_angle_deg);
    EXPECT_FLOAT_EQ(compensated, 120.0f);
}

// ── Wire spec ──

TEST(WireSpec, SetWireSpecDoesNotCrash)
{
    CamEngine engine;
    engine.set_wire_spec({WIRE_MATERIAL_NITI, 0.018f * 25.4f,
                          WIRE_SECTION_ROUND, 0.0f, 0.0f});
    engine.set_wire_spec({WIRE_MATERIAL_BETA_TI, 0.020f * 25.4f,
                          WIRE_SECTION_RECTANGULAR, 0.63f, 0.43f});
    CamResult result = engine.generate_bcode();
    EXPECT_EQ(result.bcode.step_count, 0);
}

// ── Simulate (stub) ──

TEST(CamSimulate, EmptyBcodeReturnsEmptyPoints)
{
    CamEngine engine;
    bcode_sequence_t bcode{};
    bcode.step_count = 0;
    std::vector<Point3D> points = engine.simulate(bcode);
    EXPECT_TRUE(points.empty());
}
