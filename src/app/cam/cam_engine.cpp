/**
 * @file cam_engine.cpp
 * @brief CAM algorithm orchestrator implementation
 *
 * IEC 62304 SW Class: B
 */

#include "cam_engine.h"
#include <cmath>
#include <algorithm>
#include <limits>

namespace ortho_bender {

/* ──────────────────────────────────────────────
 * Helper: 3D vector operations for Frenet-Serret frame
 * ────────────────────────────────────────────── */

namespace {

struct Vec3 {
    float x, y, z;
};

inline Vec3 sub(const Point3D& a, const Point3D& b)
{
    return {a.x - b.x, a.y - b.y, a.z - b.z};
}

inline float dot(const Vec3& a, const Vec3& b)
{
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

inline Vec3 cross(const Vec3& a, const Vec3& b)
{
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x
    };
}

inline float length(const Vec3& v)
{
    return std::sqrt(dot(v, v));
}

inline Vec3 normalize(const Vec3& v)
{
    float len = length(v);
    if (len < std::numeric_limits<float>::epsilon()) {
        return {0.0f, 0.0f, 0.0f};
    }
    return {v.x / len, v.y / len, v.z / len};
}

constexpr float kDegPerRad = 180.0f / static_cast<float>(M_PI);
constexpr float kRadPerDeg = static_cast<float>(M_PI) / 180.0f;

/**
 * @brief Rotate vector v around axis k by angle_rad (Rodrigues' rotation formula)
 *
 * v_rot = v*cos(a) + (k x v)*sin(a) + k*(k.v)*(1-cos(a))
 */
inline Vec3 rotate_around_axis(const Vec3& v, const Vec3& k, float angle_rad)
{
    float c = std::cos(angle_rad);
    float s = std::sin(angle_rad);
    Vec3 kxv = cross(k, v);
    float kdv = dot(k, v);
    return {
        v.x * c + kxv.x * s + k.x * kdv * (1.0f - c),
        v.y * c + kxv.y * s + k.y * kdv * (1.0f - c),
        v.z * c + kxv.z * s + k.z * kdv * (1.0f - c)
    };
}

} // anonymous namespace

/* ──────────────────────────────────────────────
 * Construction / Setters
 * ────────────────────────────────────────────── */

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

/* ──────────────────────────────────────────────
 * B-code generation pipeline
 * ────────────────────────────────────────────── */

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

/* ──────────────────────────────────────────────
 * discretize_curve(): Frenet-Serret frame 3D curve -> B-code
 *
 * B-code semantics: each step = (Feed L to bend point, Rotate beta, Bend theta).
 * L_mm is the wire distance fed BEFORE the bend occurs at vertex p[i].
 *
 * For consecutive tangents t_{i-1}, t_i at vertex p[i]:
 *   - L_mm   = accumulated feed distance from previous bend to p[i]
 *   - theta  = acos(clamp(dot(t_{i-1}, t_i), -1, 1))  (bend angle)
 *   - beta   = signed angle between successive binormals projected onto
 *              the plane perpendicular to the wire axis (bending plane rotation)
 *
 * After the last bend, any remaining straight segment is emitted as a
 * trailing feed step (theta=0).
 *
 * Complexity: O(N) time, O(1) extra space (writes directly to bcode array).
 * ────────────────────────────────────────────── */

bcode_sequence_t CamEngine::discretize_curve()
{
    bcode_sequence_t bcode{};
    bcode.material_id = wire_spec_.material;
    bcode.wire_diameter_mm = wire_spec_.diameter_mm;
    bcode.step_count = 0;
    bcode.total_wire_length_mm = 0.0f;

    const size_t n = target_curve_.size();
    if (n < 2) {
        return bcode;
    }

    /* Previous bending-plane normal for beta tracking.
     * Initialized to an arbitrary "up" vector; first bend establishes the reference. */
    Vec3 prev_binormal = {0.0f, 0.0f, 1.0f};
    bool first_bend = true;

    /* accumulated_L tracks the wire feed distance from the previous bend (or start)
     * up to the current bend vertex. When a bend is detected at vertex i,
     * accumulated_L holds the sum of segment lengths BEFORE vertex i. */
    float accumulated_L = 0.0f;

    Vec3 t_prev = {0.0f, 0.0f, 0.0f};
    bool have_prev = false;

    for (size_t i = 0; i < n - 1; ++i) {
        Vec3 seg = sub(target_curve_[i + 1], target_curve_[i]);
        float seg_len = length(seg);

        /* Skip degenerate (zero-length) segments */
        if (seg_len < std::numeric_limits<float>::epsilon()) {
            continue;
        }

        Vec3 t_curr = normalize(seg);

        if (!have_prev) {
            /* First valid segment: initialize tangent, start accumulating */
            t_prev = t_curr;
            accumulated_L = seg_len;
            have_prev = true;
            continue;
        }

        /* Compute bend angle theta between consecutive tangents at vertex p[i] */
        float cos_theta = std::clamp(dot(t_prev, t_curr), -1.0f, 1.0f);
        float theta_rad = std::acos(cos_theta);
        float theta_deg = theta_rad * kDegPerRad;

        /* If bend angle is negligible, treat as collinear: accumulate and move on */
        if (theta_deg < BCODE_MIN_BEND_DEG) {
            accumulated_L += seg_len;
            t_prev = t_curr;
            continue;
        }

        /* A significant bend detected at vertex p[i].
         * L_mm = accumulated feed distance UP TO this vertex (not including
         * the segment after the bend). */

        /* Compute binormal: axis of bending = cross(t_prev, t_curr) */
        Vec3 binormal = normalize(cross(t_prev, t_curr));

        /* Compute beta: rotation of bending plane around wire axis (t_prev).
         * Project current binormal and previous binormal onto the plane
         * perpendicular to t_prev, then measure the signed angle between them. */
        float beta_deg = 0.0f;
        if (!first_bend) {
            Vec3 ref_b = prev_binormal;
            float proj = dot(ref_b, t_prev);
            Vec3 ref_perp = {
                ref_b.x - proj * t_prev.x,
                ref_b.y - proj * t_prev.y,
                ref_b.z - proj * t_prev.z
            };
            float ref_len = length(ref_perp);

            proj = dot(binormal, t_prev);
            Vec3 cur_perp = {
                binormal.x - proj * t_prev.x,
                binormal.y - proj * t_prev.y,
                binormal.z - proj * t_prev.z
            };
            float cur_len = length(cur_perp);

            if (ref_len > 1e-6f && cur_len > 1e-6f) {
                ref_perp = normalize(ref_perp);
                cur_perp = normalize(cur_perp);

                float cos_beta = std::clamp(dot(ref_perp, cur_perp), -1.0f, 1.0f);
                Vec3 cross_beta = cross(ref_perp, cur_perp);
                float sin_beta = dot(cross_beta, t_prev);
                beta_deg = std::atan2(sin_beta, cos_beta) * kDegPerRad;
            }
        }
        first_bend = false;
        prev_binormal = binormal;

        /* Merge check: if accumulated feed is below minimum, defer this step.
         * We still update tangent and binormal tracking. */
        if (accumulated_L < BCODE_MIN_FEED_MM) {
            accumulated_L += seg_len;
            t_prev = t_curr;
            continue;
        }

        /* Guard against exceeding max steps */
        if (bcode.step_count >= BCODE_MAX_STEPS) {
            break;
        }

        /* Emit B-code step: feed accumulated_L then bend theta at this vertex */
        bcode_step_full_t& step = bcode.steps[bcode.step_count];
        step.L_mm = accumulated_L;
        step.beta_deg = beta_deg;
        step.theta_deg = theta_deg;
        step.theta_compensated_deg = theta_deg;  /* Pre-compensation default */

        bcode.total_wire_length_mm += accumulated_L;
        bcode.step_count++;

        /* Reset accumulator: the current segment (after this bend vertex)
         * is the start of the next feed */
        accumulated_L = seg_len;
        t_prev = t_curr;
    }

    /* Trailing straight feed after the last bend (or entire curve if no bends) */
    if (accumulated_L >= BCODE_MIN_FEED_MM && bcode.step_count < BCODE_MAX_STEPS) {
        bcode_step_full_t& step = bcode.steps[bcode.step_count];
        step.L_mm = accumulated_L;
        step.beta_deg = 0.0f;
        step.theta_deg = 0.0f;
        step.theta_compensated_deg = 0.0f;
        bcode.total_wire_length_mm += accumulated_L;
        bcode.step_count++;
    }

    return bcode;
}

/* ──────────────────────────────────────────────
 * Springback compensation
 * ────────────────────────────────────────────── */

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

/* ──────────────────────────────────────────────
 * B-code validation
 * ────────────────────────────────────────────── */

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

/* ──────────────────────────────────────────────
 * simulate(): B-code -> 3D wire shape (forward kinematics)
 *
 * Starting at origin with direction along +X and bending normal along +Z,
 * for each B-code step:
 *   1. Advance position by L_mm along current direction -> emit point
 *   2. Rotate bending normal by beta_deg around direction (wire axis rotation)
 *   3. Rotate direction by theta_compensated_deg around bending normal (bend)
 *
 * Uses Rodrigues' rotation formula for arbitrary-axis rotation.
 * Complexity: O(N) time, O(N) space for output points.
 * ────────────────────────────────────────────── */

std::vector<Point3D> CamEngine::simulate(const bcode_sequence_t& bcode)
{
    std::vector<Point3D> result;

    if (bcode.step_count == 0) {
        return result;
    }

    result.reserve(static_cast<size_t>(bcode.step_count) + 1);

    /* Initial state: origin, direction +X, bending normal +Z */
    Point3D pos = {0.0f, 0.0f, 0.0f};
    Vec3 dir = {1.0f, 0.0f, 0.0f};
    Vec3 normal = {0.0f, 0.0f, 1.0f};

    result.push_back(pos);

    for (uint16_t i = 0; i < bcode.step_count; ++i) {
        const bcode_step_full_t& step = bcode.steps[i];

        /* Step 1: Advance position along current direction by L_mm */
        pos.x += dir.x * step.L_mm;
        pos.y += dir.y * step.L_mm;
        pos.z += dir.z * step.L_mm;
        result.push_back(pos);

        /* Step 2: Rotate bending plane normal by beta_deg around wire axis (dir) */
        if (std::fabs(step.beta_deg) > std::numeric_limits<float>::epsilon()) {
            float beta_rad = step.beta_deg * kRadPerDeg;
            normal = normalize(rotate_around_axis(normal, dir, beta_rad));
        }

        /* Step 3: Bend the wire direction by theta_compensated_deg around normal */
        float theta = step.theta_compensated_deg;
        if (std::fabs(theta) > std::numeric_limits<float>::epsilon()) {
            float theta_rad = theta * kRadPerDeg;
            dir = normalize(rotate_around_axis(dir, normal, theta_rad));
        }
    }

    return result;
}

} // namespace ortho_bender
