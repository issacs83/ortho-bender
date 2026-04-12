/**
 * @file tmc5072.h
 * @brief TMC5072 dual-axis stepper motor driver -- register map and driver API
 * @author ortho-bender firmware team
 *
 * The TMC5072 is a dual-axis stepper driver+controller with two independent
 * ramp generators.  SPI protocol is 40-bit (5-byte) frames, same as TMC5160.
 * Each axis has its own register block offset by 0x20:
 *   Motor 0: base registers (e.g., RAMPMODE at 0x20, XACTUAL at 0x21)
 *   Motor 1: offset registers (e.g., RAMPMODE at 0x40, XACTUAL at 0x41)
 *
 * One physical chip controls 2 motors sharing a single SPI CS line.
 * The tmc5072_t instance stores an axis_idx (0 or 1) to select the
 * register bank.
 *
 * Reference: TMC5072 Datasheet Rev 1.12 (Trinamic/ADI)
 *
 * IEC 62304 SW Class: B
 */

#ifndef TMC5072_H
#define TMC5072_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ======================================================================
 * TMC5072 Register Addresses (Motor 0 base)
 *
 * Motor 1 registers = Motor 0 register + TMC5072_MOTOR1_OFFSET
 * ====================================================================== */

/** Offset between motor 0 and motor 1 register banks */
#define TMC5072_MOTOR1_OFFSET       0x20U

/* General configuration (shared, not per-motor) */
#define TMC5072_REG_GCONF           0x00U
#define TMC5072_REG_GSTAT           0x01U
#define TMC5072_REG_IFCNT           0x02U

/* Motor 0 velocity-dependent control */
#define TMC5072_REG_IHOLD_IRUN_0    0x10U
#define TMC5072_REG_TPOWERDOWN_0    0x11U
#define TMC5072_REG_TSTEP_0         0x12U
#define TMC5072_REG_TPWMTHRS_0      0x13U
#define TMC5072_REG_TCOOLTHRS_0     0x14U
#define TMC5072_REG_THIGH_0         0x15U

/* Motor 0 ramp generator */
#define TMC5072_REG_RAMPMODE_0      0x20U
#define TMC5072_REG_XACTUAL_0       0x21U
#define TMC5072_REG_VACTUAL_0       0x22U
#define TMC5072_REG_VSTART_0        0x23U
#define TMC5072_REG_A1_0            0x24U
#define TMC5072_REG_V1_0            0x25U
#define TMC5072_REG_AMAX_0          0x26U
#define TMC5072_REG_VMAX_0          0x27U
#define TMC5072_REG_DMAX_0          0x28U
#define TMC5072_REG_D1_0            0x2AU
#define TMC5072_REG_VSTOP_0         0x2BU
#define TMC5072_REG_TZEROWAIT_0     0x2CU
#define TMC5072_REG_XTARGET_0       0x2DU

/* Motor 0 ramp status */
#define TMC5072_REG_RAMPSTAT_0      0x35U

/* Motor 0 chopper and driver */
#define TMC5072_REG_CHOPCONF_0      0x6CU
#define TMC5072_REG_COOLCONF_0      0x6DU
#define TMC5072_REG_DRVSTATUS_0     0x6FU

/* Motor 1 velocity-dependent control (= motor 0 + 0x10) */
#define TMC5072_REG_IHOLD_IRUN_1    0x20U   /* Actually at 0x30 in real silicon */
/* NOTE: TMC5072 motor 1 register map varies from simple offset.
 * Per datasheet, motor 1 ramp regs start at 0x40:
 *   RAMPMODE_1 = 0x40, XACTUAL_1 = 0x41, etc.
 *   CHOPCONF_1 = 0x7C, DRVSTATUS_1 = 0x7F
 * We use the offset macro to compute from motor 0 addresses. */

/* Motor 1 ramp generator (motor 0 base + 0x20) */
#define TMC5072_REG_RAMPMODE_1      (TMC5072_REG_RAMPMODE_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_XACTUAL_1       (TMC5072_REG_XACTUAL_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_VACTUAL_1       (TMC5072_REG_VACTUAL_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_VSTART_1        (TMC5072_REG_VSTART_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_A1_1            (TMC5072_REG_A1_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_V1_1            (TMC5072_REG_V1_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_AMAX_1          (TMC5072_REG_AMAX_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_VMAX_1          (TMC5072_REG_VMAX_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_DMAX_1          (TMC5072_REG_DMAX_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_D1_1            (TMC5072_REG_D1_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_VSTOP_1         (TMC5072_REG_VSTOP_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_TZEROWAIT_1     (TMC5072_REG_TZEROWAIT_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_XTARGET_1       (TMC5072_REG_XTARGET_0 + TMC5072_MOTOR1_OFFSET)
#define TMC5072_REG_RAMPSTAT_1      (TMC5072_REG_RAMPSTAT_0 + TMC5072_MOTOR1_OFFSET)

/* Motor 1 chopper and driver status */
#define TMC5072_REG_CHOPCONF_1      0x7CU
#define TMC5072_REG_COOLCONF_1      0x7DU
#define TMC5072_REG_DRVSTATUS_1     0x7FU

/* Motor 1 current control */
#define TMC5072_REG_IHOLD_IRUN_1_REAL   0x30U
#define TMC5072_REG_TPOWERDOWN_1    0x31U
#define TMC5072_REG_TCOOLTHRS_1     0x34U

/* ======================================================================
 * Register Bit Definitions (shared with TMC5160 family)
 * ====================================================================== */

/* GCONF bits */
#define TMC5072_GCONF_SHAFT1        (1U << 3)   /**< Inverse direction motor 0 */
#define TMC5072_GCONF_SHAFT2        (1U << 4)   /**< Inverse direction motor 1 */
#define TMC5072_GCONF_LOCK          (1U << 7)   /**< Lock GCONF writes */

/* GSTAT bits */
#define TMC5072_GSTAT_RESET         (1U << 0)
#define TMC5072_GSTAT_DRV_ERR1      (1U << 1)   /**< Motor 0 driver error */
#define TMC5072_GSTAT_DRV_ERR2      (1U << 2)   /**< Motor 1 driver error */
#define TMC5072_GSTAT_UV_CP         (1U << 3)

/* RAMPMODE */
#define TMC5072_RAMPMODE_POSITION   0U
#define TMC5072_RAMPMODE_VEL_POS    1U
#define TMC5072_RAMPMODE_VEL_NEG    2U
#define TMC5072_RAMPMODE_HOLD       3U

/* RAMPSTAT bits */
#define TMC5072_RAMPSTAT_POS_REACHED    (1U << 9)
#define TMC5072_RAMPSTAT_VEL_REACHED    (1U << 8)
#define TMC5072_RAMPSTAT_VZERO          (1U << 10)
#define TMC5072_RAMPSTAT_SG             (1U << 6)

/* DRV_STATUS bits (same layout as TMC5160) */
#define TMC5072_DRVSTAT_SG_MASK     0x3FFU
#define TMC5072_DRVSTAT_OT          (1U << 25)
#define TMC5072_DRVSTAT_OTPW        (1U << 26)
#define TMC5072_DRVSTAT_S2GA        (1U << 24)
#define TMC5072_DRVSTAT_S2GB        (1U << 25)
#define TMC5072_DRVSTAT_OLA         (1U << 29)
#define TMC5072_DRVSTAT_OLB         (1U << 30)
#define TMC5072_DRVSTAT_STST        (1U << 31)

#define TMC5072_DRVSTAT_FAULT_MASK  (TMC5072_DRVSTAT_S2GA | TMC5072_DRVSTAT_S2GB | \
                                     TMC5072_DRVSTAT_OT)

/* IHOLD_IRUN packing (same as TMC5160) */
#define TMC5072_IHOLD_IRUN(ih, ir, id) \
    (((uint32_t)(ih) & 0x1FU) | \
     (((uint32_t)(ir) & 0x1FU) << 8) | \
     (((uint32_t)(id) & 0x0FU) << 16))

/* CHOPCONF default (SpreadCycle, 16 microsteps) */
#define TMC5072_CHOPCONF_DEFAULT    0x000100C3U

/* COOLCONF StallGuard2 threshold */
#define TMC5072_COOLCONF_SGT(t)     (((uint32_t)(t) & 0x7FU) << 16)

/* ======================================================================
 * TMC5072 Driver Instance
 * ====================================================================== */

/**
 * Per-motor TMC5072 state.
 *
 * One physical TMC5072 chip has 2 motors.  Create two tmc5072_t instances
 * sharing the same cs_index but with axis_idx = 0 and axis_idx = 1.
 */
typedef struct {
    uint8_t     axis;           /**< axis_id_t (system-level) */
    uint8_t     cs_index;       /**< SPI chip-select index (shared between axes) */
    uint8_t     axis_idx;       /**< Motor index within the chip (0 or 1) */
    bool        initialized;    /**< Driver initialized flag */
    bool        enabled;        /**< Motor outputs enabled */
    uint32_t    drv_status;     /**< Cached DRV_STATUS */
    uint16_t    sg_result;      /**< Cached StallGuard2 result */
    int32_t     xactual;        /**< Cached XACTUAL */
} tmc5072_t;

/* ======================================================================
 * Driver API
 * ====================================================================== */

/**
 * @brief Initialize TMC5072 driver for one motor axis
 * @param tmc       Pointer to driver instance (caller-allocated, static)
 * @param axis      System axis_id_t
 * @param cs_index  SPI chip-select index
 * @param axis_idx  Motor index within chip (0 or 1)
 * @return true on success
 *
 * Configures GCONF, CHOPCONF, current, and ramp defaults for the
 * specified motor within the dual-axis chip.
 */
bool tmc5072_init(tmc5072_t *tmc, uint8_t axis, uint8_t cs_index,
                  uint8_t axis_idx);

/**
 * @brief Write a TMC5072 register
 * @param tmc   Driver instance
 * @param reg   Register address (0x00-0x7F)
 * @param value 32-bit register value
 */
void tmc5072_write_reg(tmc5072_t *tmc, uint8_t reg, uint32_t value);

/**
 * @brief Read a TMC5072 register
 * @param tmc  Driver instance
 * @param reg  Register address
 * @return 32-bit register value
 */
uint32_t tmc5072_read_reg(tmc5072_t *tmc, uint8_t reg);

/**
 * @brief Move to absolute position (position mode)
 * @param tmc      Driver instance
 * @param position Target position in microsteps
 */
void tmc5072_move_to(tmc5072_t *tmc, int32_t position);

/**
 * @brief Check if target position has been reached
 * @param tmc  Driver instance
 * @return true if position reached
 */
bool tmc5072_position_reached(tmc5072_t *tmc);

/**
 * @brief Get current actual position
 * @param tmc  Driver instance
 * @return Current position in microsteps
 */
int32_t tmc5072_get_position(tmc5072_t *tmc);

/**
 * @brief Set current position without moving
 * @param tmc      Driver instance
 * @param position New position value
 */
void tmc5072_set_position(tmc5072_t *tmc, int32_t position);

/**
 * @brief Set ramp parameters
 * @param tmc   Driver instance
 * @param vmax  Maximum velocity
 * @param amax  Maximum acceleration
 * @param dmax  Maximum deceleration
 */
void tmc5072_set_ramp(tmc5072_t *tmc, uint32_t vmax, uint32_t amax,
                      uint32_t dmax);

/**
 * @brief Stop motion (decelerate to zero)
 * @param tmc  Driver instance
 */
void tmc5072_stop(tmc5072_t *tmc);

/**
 * @brief Enable motor outputs
 * @param tmc  Driver instance
 */
void tmc5072_enable(tmc5072_t *tmc);

/**
 * @brief Disable motor outputs
 * @param tmc  Driver instance
 */
void tmc5072_disable(tmc5072_t *tmc);

/**
 * @brief Poll DRV_STATUS and cache results
 * @param tmc  Driver instance
 * @return DRV_STATUS register value
 */
uint32_t tmc5072_poll_status(tmc5072_t *tmc);

/**
 * @brief Check if any driver fault is active
 * @param tmc  Driver instance
 * @return true if fault detected
 */
bool tmc5072_has_fault(const tmc5072_t *tmc);

/**
 * @brief Set motor current
 * @param tmc        Driver instance
 * @param ihold      Hold current (0-31)
 * @param irun       Run current (0-31)
 * @param iholddelay Hold delay (0-15)
 */
void tmc5072_set_current(tmc5072_t *tmc, uint8_t ihold, uint8_t irun,
                         uint8_t iholddelay);

/**
 * @brief Configure StallGuard2 threshold
 * @param tmc       Driver instance
 * @param threshold SGT value (signed, -64 to +63)
 */
void tmc5072_set_stallguard(tmc5072_t *tmc, int8_t threshold);

/**
 * @brief Clear GSTAT error flags
 * @param tmc  Driver instance
 */
void tmc5072_clear_errors(tmc5072_t *tmc);

/**
 * @brief Get motor HAL ops for TMC5072
 * @return Pointer to static motor_hal_ops_t
 */
struct motor_hal_ops;
const struct motor_hal_ops *tmc5072_get_motor_hal_ops(void);

#ifdef __cplusplus
}
#endif

#endif /* TMC5072_H */
