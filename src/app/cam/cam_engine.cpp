/**
 * @file cam_engine.cpp
 * @brief CAM algorithm orchestrator implementation
 *
 * IEC 62304 SW Class: B
 */

#include "cam_engine.h"
#include <cmath>
#include <algorithm>

namespace ortho_bender {

CamEngine::CamEngine()
    : wire_spec_{WIRE_MATERIAL_SS304, 0.016f * 25.4f, WIRE_SECTION_ROUND, 0.0f, 0.0f}
{
}

CamEngine::~CamEngine() = default;

void CamEngine::set_target_curve(const std::vector<Point3D>& points)
{
    target_curve_ = points;
}

void CamEngine::set_wire_spec(const WireSpec& spec)
{
    wire_spec_ = spec;
}

CamResult CamEngine::generate_bcode()
{
    CamResult result{};

    /* Step 1: Discretize 3D curve into B-code steps */
    result.bcode = discretize_curve();

    /* Step 2: Apply springback compensation */
    apply_springback_compensation(result.bcode);

    /* Step 3: Validate */
    bcode_validation_t validation = validate_bcode(result.bcode);
    if (validation != BCODE_VALID) {
        result.warnings = "B-code validation failed: code " +
                          std::to_string(static_cast<int>(validation));
    }

    return result;
}

bcode_sequence_t CamEngine::discretize_curve()
{
    bcode_sequence_t bcode{};
    bcode.material_id = wire_spec_.material;
    bcode.wire_diameter_mm = wire_spec_.diameter_mm;

    /* TODO: Implement 3D curve -> B-code discretization algorithm
     *
     * Algorithm outline:
     * 1. Walk along curve points
     * 2. At each segment change, compute:
     *    - L: distance along wire between bends
     *    - beta: rotation of bending plane
     *    - theta: bend angle
     * 3. Use Frenet-Serret frame for local coordinate system
     */

    return bcode;
}

void CamEngine::apply_springback_compensation(bcode_sequence_t& bcode)
{
    const wire_properties_t *props = wire_get_properties(
        static_cast<wire_material_t>(bcode.material_id));

    if (!props) {
        return;
    }

    for (uint16_t i = 0; i < bcode.step_count; i++) {
        float theta = bcode.steps[i].theta_deg;

        /* Apply springback ratio: compensated = original / (1 - K)
         * where K is the springback ratio */
        float compensated = theta / (1.0f - props->springback_ratio);

        /* Clamp to max bend angle */
        compensated = std::min(compensated, props->max_bend_angle_deg);

        bcode.steps[i].theta_compensated_deg = compensated;
    }
}

bcode_validation_t CamEngine::validate_bcode(const bcode_sequence_t& bcode)
{
    if (bcode.step_count > BCODE_MAX_STEPS) {
        return BCODE_ERR_TOO_MANY_STEPS;
    }

    float total_length = 0.0f;

    for (uint16_t i = 0; i < bcode.step_count; i++) {
        const auto& step = bcode.steps[i];

        if (step.L_mm < BCODE_MIN_FEED_MM || step.L_mm > BCODE_MAX_FEED_MM) {
            return BCODE_ERR_FEED_OUT_OF_RANGE;
        }

        if (step.theta_deg > BCODE_MAX_BEND_DEG) {
            return BCODE_ERR_BEND_OUT_OF_RANGE;
        }

        total_length += step.L_mm;
    }

    if (total_length > FEED_SOFT_LIMIT_MAX_MM) {
        return BCODE_ERR_TOTAL_LENGTH_EXCEEDED;
    }

    return BCODE_VALID;
}

std::vector<Point3D> CamEngine::simulate(const bcode_sequence_t& bcode)
{
    std::vector<Point3D> result;

    /* TODO: Implement wire shape simulation from B-code
     *
     * Algorithm outline:
     * 1. Start at origin with wire direction along +X
     * 2. For each B-code step:
     *    a. Advance position by L along current direction
     *    b. Rotate bending plane by beta around wire axis
     *    c. Bend by theta_compensated in current bending plane
     * 3. Collect resulting 3D points
     */

    return result;
}

} // namespace ortho_bender
