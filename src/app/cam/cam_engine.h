/**
 * @file cam_engine.h
 * @brief CAM algorithm orchestrator
 * @note Converts 3D wire shape -> B-code with springback compensation
 *
 * IEC 62304 SW Class: B
 */

#ifndef CAM_ENGINE_H
#define CAM_ENGINE_H

#include <cstdint>
#include <vector>
#include <string>

extern "C" {
#include "bcode_types.h"
#include "machine_config.h"
#include "wire_materials.h"
}

namespace ortho_bender {

/**
 * @brief 3D point in wire coordinate space
 */
struct Point3D {
    float x;    /**< mm */
    float y;    /**< mm */
    float z;    /**< mm */
};

/**
 * @brief Wire specification for CAM processing
 */
struct WireSpec {
    wire_material_t material;
    float           diameter_mm;
    wire_section_t  section;    /**< Round or rectangular */
    float           width_mm;   /**< For rectangular only */
    float           height_mm;  /**< For rectangular only */
};

/**
 * @brief CAM processing result
 */
struct CamResult {
    bcode_sequence_t    bcode;
    float               estimated_accuracy_deg;
    float               estimated_accuracy_mm;
    std::string         warnings;
};

/**
 * @brief Main CAM engine class
 *
 * Workflow:
 * 1. Load target 3D curve (point cloud or spline)
 * 2. Set wire specification (material, diameter)
 * 3. Generate B-code sequence
 * 4. Apply springback compensation
 * 5. Validate and return result
 */
class CamEngine {
public:
    CamEngine();
    ~CamEngine();

    /**
     * @brief Set target wire shape from 3D points
     */
    void set_target_curve(const std::vector<Point3D>& points);

    /**
     * @brief Set wire specification
     */
    void set_wire_spec(const WireSpec& spec);

    /**
     * @brief Generate B-code from target curve
     * @return CamResult with B-code sequence and quality metrics
     */
    CamResult generate_bcode();

    /**
     * @brief Simulate the resulting wire shape from B-code
     * @return Predicted 3D points after bending
     */
    std::vector<Point3D> simulate(const bcode_sequence_t& bcode);

private:
    std::vector<Point3D>    target_curve_;
    WireSpec                wire_spec_;

    /* Internal stages */
    bcode_sequence_t discretize_curve();
    void apply_springback_compensation(bcode_sequence_t& bcode);
    bcode_validation_t validate_bcode(const bcode_sequence_t& bcode);
};

} // namespace ortho_bender

#endif /* CAM_ENGINE_H */
