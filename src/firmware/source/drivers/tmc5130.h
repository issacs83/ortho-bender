/**
 * @file tmc5130.h
 * @brief TMC5130 stepper motor driver -- register map and driver API
 * @author ortho-bender firmware team
 *
 * The TMC5130 is a single-axis stepper driver+controller with internal ramp
 * generator.  Register map is largely compatible with TMC5160, but the TMC5130
 * has lower current capability and no high-side sense resistor support.
 *
 * SPI protocol: 40-bit (5-byte) frames, identical to TMC5160.
 *
 * Key differences from TMC5160:
 *   - No S2VS (short-to-supply) detection in DRV_STATUS
 *   - Different PWMCONF register layout
 *   - Lower maximum current capability
 *   - CHOPCONF register compatible but different default recommendations
 *
 * Reference: TMC5130 Datasheet Rev 1.19 (Trinamic/ADI)
 *
 * IEC 62304 SW Class: B
 */

#ifndef TMC5130_H
#define TMC5130_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ======================================================================
 * TMC5130 Register Addresses
 *
 * Register map is compatible with TMC5160 for the common registers.
 * We define TMC5130-specific names for clarity and use the same numeric
 * addresses where they match.
 * ====================================================================== */

/* General */
#define TMC5130_REG_GCONF           0x00U
#define TMC5130_REG_GSTAT           0x01U
#define TMC5130_REG_IOIN            0x04U

/* Velocity dependent control */
#define TMC5130_REG_IHOLD_IRUN      0x10U
#define TMC5130_REG_TPOWERDOWN      0x11U
#define TMC5130_REG_TSTEP           0x12U
#define TMC5130_REG_TPWMTHRS        0x13U
#define TMC5130_REG_TCOOLTHRS       0x14U
#define TMC5130_REG_THIGH           0x15U

/* Ramp generator registers */
#define TMC5130_REG_RAMPMODE        0x20U
#define TMC5130_REG_XACTUAL         0x21U
#define TMC5130_REG_VACTUAL         0x22U
#define TMC5130_REG_VSTART          0x23U
#define TMC5130_REG_A1              0x24U
#define TMC5130_REG_V1              0x25U
#define TMC5130_REG_AMAX            0x26U
#define TMC5130_REG_VMAX            0x27U
#define TMC5130_REG_DMAX            0x28U
#define TMC5130_REG_D1              0x2AU
#define TMC5130_REG_VSTOP           0x2BU
#define TMC5130_REG_TZEROWAIT       0x2CU
#define TMC5130_REG_XTARGET         0x2DU

/* Ramp generator status */
#define TMC5130_REG_RAMPSTAT        0x35U

/* Chopper and driver */
#define TMC5130_REG_CHOPCONF        0x6CU
#define TMC5130_REG_COOLCONF        0x6DU
#define TMC5130_REG_DRVSTATUS       0x6FU
#define TMC5130_REG_PWMCONF         0x70U

/* ======================================================================
 * Register Bit Definitions
 * ====================================================================== */

/* GCONF bits */
#define TMC5130_GCONF_EN_PWM_MODE   (1U << 2)
#define TMC5130_GCONF_MULTISTEP     (1U << 3)
#define TMC5130_GCONF_SHAFT         (1U << 4)
#define TMC5130_GCONF_DIAG0_STALL   (1U << 7)
#define TMC5130_GCONF_DIAG1_STALL   (1U << 8)

/* GSTAT bits */
#define TMC5130_GSTAT_RESET         (1U << 0)
#define TMC5130_GSTAT_DRV_ERR       (1U << 1)
#define TMC5130_GSTAT_UV_CP         (1U << 2)

/* RAMPMODE */
#define TMC5130_RAMPMODE_POSITION   0U
#define TMC5130_RAMPMODE_VEL_POS    1U
#define TMC5130_RAMPMODE_VEL_NEG    2U
#define TMC5130_RAMPMODE_HOLD       3U

/* RAMPSTAT bits */
#define TMC5130_RAMPSTAT_POS_REACHED    (1U << 9)
#define TMC5130_RAMPSTAT_VEL_REACHED    (1U << 8)
#define TMC5130_RAMPSTAT_VZERO          (1U << 10)
#define TMC5130_RAMPSTAT_SG             (1U << 6)

/* DRV_STATUS bits (TMC5130 -- no S2VSA/S2VSB compared to TMC5160) */
#define TMC5130_DRVSTAT_SG_MASK     0x3FFU
#define TMC5130_DRVSTAT_CS_SHIFT    16
#define TMC5130_DRVSTAT_CS_MASK     (0x1FU << 16)
#define TMC5130_DRVSTAT_OT          (1U << 25)
#define TMC5130_DRVSTAT_OTPW        (1U << 26)
#define TMC5130_DRVSTAT_S2GA        (1U << 24)
#define TMC5130_DRVSTAT_S2GB        (1U << 25)
#define TMC5130_DRVSTAT_OLA         (1U << 29)
#define TMC5130_DRVSTAT_OLB         (1U << 30)
#define TMC5130_DRVSTAT_STST        (1U << 31)

#define TMC5130_DRVSTAT_FAULT_MASK  (TMC5130_DRVSTAT_S2GA | TMC5130_DRVSTAT_S2GB | \
                                     TMC5130_DRVSTAT_OT)

/* IHOLD_IRUN packing */
#define TMC5130_IHOLD_IRUN(ih, ir, id) \
    (((uint32_t)(ih) & 0x1FU) | \
     (((uint32_t)(ir) & 0x1FU) << 8) | \
     (((uint32_t)(id) & 0x0FU) << 16))

/* CHOPCONF default (SpreadCycle, 16 microsteps) */
#define TMC5130_CHOPCONF_DEFAULT    0x000100C3U

/* COOLCONF StallGuard2 threshold */
#define TMC5130_COOLCONF_SGT(t)     (((uint32_t)(t) & 0x7FU) << 16)

/* ======================================================================
 * TMC5130 Driver Instance
 * ====================================================================== */

/** Per-axis TMC5130 state */
typedef struct {
    uint8_t     axis;           /**< axis_id_t */
    uint8_t     cs_index;       /**< SPI chip-select index */
    bool        initialized;    /**< Driver initialized flag */
    bool        enabled;        /**< Motor outputs enabled */
    uint32_t    drv_status;     /**< Cached DRV_STATUS */
    uint16_t    sg_result;      /**< Cached StallGuard2 result */
    uint16_t    cs_actual;      /**< Cached actual current */
    int32_t     xactual;        /**< Cached XACTUAL */
} tmc5130_t;

/* ======================================================================
 * Driver API
 * ====================================================================== */

/**
 * @brief Initialize TMC5130 driver for a specific axis
 * @param tmc       Pointer to driver instance (caller-allocated, static)
 * @param axis      axis_id_t
 * @param cs_index  SPI chip-select index
 * @return true on success
 */
bool tmc5130_init(tmc5130_t *tmc, uint8_t axis, uint8_t cs_index);

/**
 * @brief Write a TMC5130 register
 */
void tmc5130_write_reg(tmc5130_t *tmc, uint8_t reg, uint32_t value);

/**
 * @brief Read a TMC5130 register
 */
uint32_t tmc5130_read_reg(tmc5130_t *tmc, uint8_t reg);

/**
 * @brief Enable motor outputs
 */
void tmc5130_enable(tmc5130_t *tmc);

/**
 * @brief Disable motor outputs
 */
void tmc5130_disable(tmc5130_t *tmc);

/**
 * @brief Set motor current
 */
void tmc5130_set_current(tmc5130_t *tmc, uint8_t ihold, uint8_t irun,
                         uint8_t iholddelay);

/**
 * @brief Set ramp parameters
 */
void tmc5130_set_ramp(tmc5130_t *tmc, uint32_t vmax, uint32_t amax,
                      uint32_t dmax);

/**
 * @brief Move to absolute position (position mode)
 */
void tmc5130_move_to(tmc5130_t *tmc, int32_t position);

/**
 * @brief Stop motion (decelerate to zero)
 */
void tmc5130_stop(tmc5130_t *tmc);

/**
 * @brief Check if target position has been reached
 */
bool tmc5130_position_reached(tmc5130_t *tmc);

/**
 * @brief Get current actual position
 */
int32_t tmc5130_get_position(tmc5130_t *tmc);

/**
 * @brief Set current position without moving
 */
void tmc5130_set_position(tmc5130_t *tmc, int32_t position);

/**
 * @brief Configure StallGuard2 threshold
 */
void tmc5130_set_stallguard(tmc5130_t *tmc, int8_t threshold);

/**
 * @brief Poll DRV_STATUS and cache results
 */
uint32_t tmc5130_poll_status(tmc5130_t *tmc);

/**
 * @brief Check if any driver fault is active
 */
bool tmc5130_has_fault(const tmc5130_t *tmc);

/**
 * @brief Clear GSTAT error flags
 */
void tmc5130_clear_errors(tmc5130_t *tmc);

/**
 * @brief Set chopper configuration
 */
void tmc5130_set_chopconf(tmc5130_t *tmc, uint32_t chopconf);

/**
 * @brief Get motor HAL ops for TMC5130
 * @return Pointer to static motor_hal_ops_t
 */
struct motor_hal_ops;
const struct motor_hal_ops *tmc5130_get_motor_hal_ops(void);

#ifdef __cplusplus
}
#endif

#endif /* TMC5130_H */
