"""
Wire material database. Ported from src/shared/wire_materials.c.
"""

MATERIALS = {
    0: {
        "id": 0, "name": "SS304", "label": "Stainless Steel 304",
        "youngs_modulus_gpa": 177.0,
        "yield_strength_mpa": 515.0,
        "ultimate_strength_mpa": 860.0,
        "elongation_pct": 8.0,
        "springback_ratio": 0.15,
        "requires_heating": False,
        "af_temperature_c": 0.0,
        "min_bend_radius_factor": 1.5,
        "max_bend_angle_deg": 160.0,
    },
    1: {
        "id": 1, "name": "NiTi", "label": "Nickel-Titanium",
        "youngs_modulus_gpa": 41.0,
        "yield_strength_mpa": 195.0,
        "ultimate_strength_mpa": 895.0,
        "elongation_pct": 10.0,
        "springback_ratio": 0.60,
        "requires_heating": True,
        "af_temperature_c": 35.0,
        "min_bend_radius_factor": 3.0,
        "max_bend_angle_deg": 120.0,
    },
    2: {
        "id": 2, "name": "Beta-Ti", "label": "Beta-Titanium (TMA)",
        "youngs_modulus_gpa": 69.0,
        "yield_strength_mpa": 930.0,
        "ultimate_strength_mpa": 1150.0,
        "elongation_pct": 12.0,
        "springback_ratio": 0.25,
        "requires_heating": False,
        "af_temperature_c": 0.0,
        "min_bend_radius_factor": 2.0,
        "max_bend_angle_deg": 150.0,
    },
    3: {
        "id": 3, "name": "CuNiTi", "label": "Copper-Nickel-Titanium",
        "youngs_modulus_gpa": 41.0,
        "yield_strength_mpa": 195.0,
        "ultimate_strength_mpa": 895.0,
        "elongation_pct": 10.0,
        "springback_ratio": 0.55,
        "requires_heating": True,
        "af_temperature_c": 27.0,
        "min_bend_radius_factor": 3.0,
        "max_bend_angle_deg": 120.0,
    },
}


def get_material(material_id: int) -> dict | None:
    return MATERIALS.get(material_id)


def get_all_materials() -> list[dict]:
    return list(MATERIALS.values())
