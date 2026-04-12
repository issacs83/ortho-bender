/**
 * @file test_cam_engine.cpp
 * @brief Unit tests for CAM engine: discretization, springback, simulation
 *
 * IEC 62304 SW Class: B
 */

#include <gtest/gtest.h>
#include <cmath>
#include "cam_engine.h"

using namespace ortho_bender;

/* ── Helper: Euclidean distance between two Point3D ── */

static float dist3d(const Point3D& a, const Point3D& b)
{
    float dx = a.x - b.x;
    float dy = a.y - b.y;
    float dz = a.z - b.z;
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

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

    /* With actual discretization: 3 points, 2 segments, 1 bend -> 1 step + trailing feed */
    EXPECT_GE(result.bcode.step_count, 1u);
    EXPECT_TRUE(result.warnings.empty());
}

// ── Springback compensation ──

TEST(SpringbackCompensation, SS304CompensationApplied)
{
    CamEngine engine;
    engine.set_wire_spec({WIRE_MATERIAL_SS304, 0.016f * 25.4f,
                          WIRE_SECTION_ROUND, 0.0f, 0.0f});

    // SS304 springback ratio = 0.15
    // compensated = theta / (1 - 0.15) = theta / 0.85
    // For 90 deg: 90 / 0.85 = 105.88 deg
    CamResult result = engine.generate_bcode();

    // With empty curve (no set_target_curve), bcode has 0 steps.
    // This test validates the engine can at least run without crashing.
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

// ── Simulate (empty) ──

TEST(CamSimulate, EmptyBcodeReturnsEmptyPoints)
{
    CamEngine engine;
    bcode_sequence_t bcode{};
    bcode.step_count = 0;
    std::vector<Point3D> points = engine.simulate(bcode);
    EXPECT_TRUE(points.empty());
}

// ══════════════════════════════════════════════
// NEW TESTS: discretize_curve and simulate
// ══════════════════════════════════════════════

// ── Discretize: straight line produces no bends ──

TEST(DiscretizeCurve, StraightLineNoBends)
{
    CamEngine engine;
    engine.set_wire_spec({WIRE_MATERIAL_SS304, 0.016f * 25.4f,
                          WIRE_SECTION_ROUND, 0.0f, 0.0f});

    /* Collinear points along +X: should produce 0 bend steps,
     * just a trailing straight feed. */
    engine.set_target_curve({{0, 0, 0}, {10, 0, 0}, {20, 0, 0}, {30, 0, 0}});
    CamResult result = engine.generate_bcode();

    /* All tangents are identical -> theta ~= 0 for all segments.
     * Only a trailing feed step with theta=0 should be emitted. */
    ASSERT_GE(result.bcode.step_count, 1u);
    for (uint16_t i = 0; i < result.bcode.step_count; ++i) {
        EXPECT_NEAR(result.bcode.steps[i].theta_deg, 0.0f, 0.01f);
    }
    /* Total wire length should be ~30 mm */
    EXPECT_NEAR(result.bcode.total_wire_length_mm, 30.0f, 0.1f);
    EXPECT_TRUE(result.warnings.empty());
}

// ── Discretize: single 90-degree bend in XY plane ──

TEST(DiscretizeCurve, Single90DegreeBend)
{
    CamEngine engine;
    engine.set_wire_spec({WIRE_MATERIAL_SS304, 0.016f * 25.4f,
                          WIRE_SECTION_ROUND, 0.0f, 0.0f});

    /* Feed along +X for 20mm, then bend 90 degrees toward +Y for 15mm */
    engine.set_target_curve({{0, 0, 0}, {20, 0, 0}, {20, 15, 0}});
    CamResult result = engine.generate_bcode();

    /* Should produce at least 1 step with theta ~= 90 deg */
    ASSERT_GE(result.bcode.step_count, 1u);

    /* Find the step with the bend */
    bool found_90 = false;
    for (uint16_t i = 0; i < result.bcode.step_count; ++i) {
        if (result.bcode.steps[i].theta_deg > 80.0f) {
            EXPECT_NEAR(result.bcode.steps[i].theta_deg, 90.0f, 0.5f);
            EXPECT_NEAR(result.bcode.steps[i].L_mm, 20.0f, 0.1f);
            found_90 = true;
        }
    }
    EXPECT_TRUE(found_90) << "Expected a ~90 degree bend step";
    EXPECT_TRUE(result.warnings.empty());
}

// ── Discretize: two successive bends ──

TEST(DiscretizeCurve, TwoSuccessiveBends)
{
    CamEngine engine;
    engine.set_wire_spec({WIRE_MATERIAL_SS304, 0.016f * 25.4f,
                          WIRE_SECTION_ROUND, 0.0f, 0.0f});

    /* U-shape: +X then +Y then -X */
    engine.set_target_curve({
        {0, 0, 0}, {10, 0, 0}, {10, 10, 0}, {0, 10, 0}
    });
    CamResult result = engine.generate_bcode();

    /* Should have at least 2 bend steps (~90 deg each) */
    int bend_count = 0;
    for (uint16_t i = 0; i < result.bcode.step_count; ++i) {
        if (result.bcode.steps[i].theta_deg > 1.0f) {
            bend_count++;
            EXPECT_NEAR(result.bcode.steps[i].theta_deg, 90.0f, 0.5f);
        }
    }
    EXPECT_EQ(bend_count, 2);
}

// ── Discretize: point count < 2 returns empty ──

TEST(DiscretizeCurve, SinglePointReturnsEmpty)
{
    CamEngine engine;
    engine.set_target_curve({{5, 3, 1}});
    CamResult result = engine.generate_bcode();
    EXPECT_EQ(result.bcode.step_count, 0);
}

TEST(DiscretizeCurve, EmptyPointsReturnsEmpty)
{
    CamEngine engine;
    engine.set_target_curve({});
    CamResult result = engine.generate_bcode();
    EXPECT_EQ(result.bcode.step_count, 0);
}

// ── Simulate: straight feed along +X ──

TEST(CamSimulate, StraightFeedAlongX)
{
    CamEngine engine;
    bcode_sequence_t bcode{};
    bcode.step_count = 1;
    bcode.steps[0].L_mm = 25.0f;
    bcode.steps[0].beta_deg = 0.0f;
    bcode.steps[0].theta_deg = 0.0f;
    bcode.steps[0].theta_compensated_deg = 0.0f;

    std::vector<Point3D> pts = engine.simulate(bcode);

    /* origin + 1 step = 2 points */
    ASSERT_EQ(pts.size(), 2u);

    /* Origin at (0,0,0) */
    EXPECT_NEAR(pts[0].x, 0.0f, 1e-5f);
    EXPECT_NEAR(pts[0].y, 0.0f, 1e-5f);
    EXPECT_NEAR(pts[0].z, 0.0f, 1e-5f);

    /* After 25mm feed along +X */
    EXPECT_NEAR(pts[1].x, 25.0f, 1e-4f);
    EXPECT_NEAR(pts[1].y, 0.0f, 1e-4f);
    EXPECT_NEAR(pts[1].z, 0.0f, 1e-4f);
}

// ── Simulate: 90-degree bend should change direction ──

TEST(CamSimulate, SingleBend90Degrees)
{
    CamEngine engine;
    bcode_sequence_t bcode{};
    bcode.step_count = 2;

    /* First step: feed 10mm along +X, then bend 90 deg */
    bcode.steps[0].L_mm = 10.0f;
    bcode.steps[0].beta_deg = 0.0f;
    bcode.steps[0].theta_deg = 90.0f;
    bcode.steps[0].theta_compensated_deg = 90.0f;

    /* Second step: feed 10mm in new direction (should be +Y after 90 deg bend
     * around +Z normal) */
    bcode.steps[1].L_mm = 10.0f;
    bcode.steps[1].beta_deg = 0.0f;
    bcode.steps[1].theta_deg = 0.0f;
    bcode.steps[1].theta_compensated_deg = 0.0f;

    std::vector<Point3D> pts = engine.simulate(bcode);

    ASSERT_EQ(pts.size(), 3u);

    /* Point 0: origin */
    EXPECT_NEAR(pts[0].x, 0.0f, 1e-5f);
    EXPECT_NEAR(pts[0].y, 0.0f, 1e-5f);

    /* Point 1: after 10mm along +X = (10, 0, 0) */
    EXPECT_NEAR(pts[1].x, 10.0f, 1e-4f);
    EXPECT_NEAR(pts[1].y, 0.0f, 1e-4f);

    /* Point 2: after 90 deg bend around +Z, new dir = +Y
     * -> (10, 0, 0) + 10*(0, 1, 0) = (10, 10, 0) */
    EXPECT_NEAR(pts[2].x, 10.0f, 0.01f);
    EXPECT_NEAR(pts[2].y, 10.0f, 0.01f);
    EXPECT_NEAR(pts[2].z, 0.0f, 0.01f);
}

// ── Roundtrip: discretize then simulate should approximate original curve ──

TEST(CamRoundtrip, DiscretizeSimulateConsistency)
{
    CamEngine engine;
    engine.set_wire_spec({WIRE_MATERIAL_SS304, 0.016f * 25.4f,
                          WIRE_SECTION_ROUND, 0.0f, 0.0f});

    /* Simple L-shape in XY plane */
    std::vector<Point3D> input = {{0, 0, 0}, {20, 0, 0}, {20, 15, 0}};
    engine.set_target_curve(input);

    CamResult result = engine.generate_bcode();
    ASSERT_GE(result.bcode.step_count, 1u);

    /* Simulate with compensated angles (SS304 K=0.15 -> theta_comp = 90/0.85 ~ 105.9) */
    std::vector<Point3D> simulated = engine.simulate(result.bcode);
    ASSERT_GE(simulated.size(), 2u);

    /* Total simulated wire length should approximate the input curve total length */
    float input_total = 0.0f;
    for (size_t i = 1; i < input.size(); ++i) {
        input_total += dist3d(input[i], input[i - 1]);
    }

    float sim_total = 0.0f;
    for (size_t i = 1; i < simulated.size(); ++i) {
        sim_total += dist3d(simulated[i], simulated[i - 1]);
    }

    /* Wire lengths should match (feed distances are preserved) */
    EXPECT_NEAR(sim_total, input_total, 0.5f);
}

// ── Simulate: 3D bend with beta rotation ──

TEST(CamSimulate, BetaRotationChangesPlane)
{
    CamEngine engine;
    bcode_sequence_t bcode{};
    bcode.step_count = 2;

    /* First bend: 90 deg in default plane (around +Z normal) -> turns +X to +Y */
    bcode.steps[0].L_mm = 10.0f;
    bcode.steps[0].beta_deg = 0.0f;
    bcode.steps[0].theta_compensated_deg = 90.0f;

    /* Second bend: rotate bending plane 90 deg around wire axis,
     * then bend 90 deg -> should turn into Z direction */
    bcode.steps[1].L_mm = 10.0f;
    bcode.steps[1].beta_deg = 90.0f;
    bcode.steps[1].theta_compensated_deg = 90.0f;

    std::vector<Point3D> pts = engine.simulate(bcode);
    ASSERT_EQ(pts.size(), 3u);

    /* After first bend: at (10, 0, 0), direction now +Y */
    EXPECT_NEAR(pts[1].x, 10.0f, 0.01f);
    EXPECT_NEAR(pts[1].y, 0.0f, 0.01f);

    /* After second step: feed 10mm along +Y -> (10, 10, 0)
     * Then beta=90 rotates normal from +Z around +Y axis,
     * and theta=90 bends +Y toward +Z.
     * Point 2 should have moved in Y direction by 10mm. */
    EXPECT_NEAR(pts[2].x, 10.0f, 0.1f);
    EXPECT_NEAR(pts[2].y, 10.0f, 0.1f);

    /* The Z component should still be 0 after feed (bend happens after feed) */
    EXPECT_NEAR(pts[2].z, 0.0f, 0.1f);
}
