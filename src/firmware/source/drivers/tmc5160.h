/**
 * @file tmc5160.h
 * @brief TMC5160 stepper motor driver — register map and driver API
 * @note Communicates with TMC5160 via SPI through hal_spi.h abstraction.
 *       Uses internal ramp generator (position mode) — no PID needed.
 *
 * Reference: TMC5160 Datasheet Rev 1.17 (Trinamic/ADI)
 *
 * IEC 62304 SW Class: B
 */

#ifndef TMC5160_H
#define TMC5160_H

#include <stdint.h>
#include <stdbool.h>
#include "ipc_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────
 * TMC5160 Register Addresses
 * ────────────────────────────────────────────── */

/* General */
#define TMC_REG_GCONF           0x00
#define TMC_REG_GSTAT           0x01
#define TMC_REG_IOIN            0x04

/* Velocity dependent control */
#define TMC_REG_IHOLD_IRUN      0x10
#define TMC_REG_TPOWERDOWN      0x11
#define TMC_REG_TSTEP           0x12
#define TMC_REG_TPWMTHRS        0x13
#define TMC_REG_TCOOLTHRS       0x14
#define TMC_REG_THIGH           0x15

/* Ramp generator registers */
#define TMC_REG_RAMPMODE        0x20
#define TMC_REG_XACTUAL         0x21
#define TMC_REG_VACTUAL         0x22
#define TMC_REG_VSTART          0x23
#define TMC_REG_A1              0x24
#define TMC_REG_V1              0x25
#define TMC_REG_AMAX            0x26
#define TMC_REG_VMAX            0x27
#define TMC_REG_DMAX            0x28
#define TMC_REG_D1              0x2A
#define TMC_REG_VSTOP           0x2B
#define TMC_REG_TZEROWAIT       0x2C
#define TMC_REG_XTARGET         0x2D

/* Ramp generator status */
#define TMC_REG_RAMPSTAT        0x35
#define TMC_REG_XLATCH          0x36

/* Encoder */
#define TMC_REG_ENCMODE         0x38
#define TMC_REG_XENC            0x39

/* Chopper and driver configuration */
#define TMC_REG_CHOPCONF        0x6C
#define TMC_REG_COOLCONF        0x6D
#define TMC_REG_DCCTRL          0x6E
#define TMC_REG_DRVSTATUS       0x6F
#define TMC_REG_PWMCONF         0x70

/* StallGuard */
#define TMC_REG_SG_RESULT       0x41    /* Not a direct register — read from DRV_STATUS */

/* ──────────────────────────────────────────────
 * Register Bit Definitions
 * ────────────────────────────────────────────── */

/* GCONF bits */
#define GCONF_EN_PWM_MODE       (1U << 2)   /* StealthChop enable */
#define GCONF_MULTISTEP_FILT    (1U << 3)   /* Step pulse filter */
#define GCONF_SHAFT             (1U << 4)   /* Inverse motor direction */
#define GCONF_DIAG0_INT_PUSH    (1U << 6)   /* DIAG0 = active-low open-drain */
#define GCONF_DIAG0_STALL       (1U << 7)   /* DIAG0 = StallGuard2 output */
#define GCONF_DIAG1_STALL       (1U << 8)   /* DIAG1 = StallGuard2 output */

/* GSTAT bits */
#define GSTAT_RESET             (1U << 0)
#define GSTAT_DRV_ERR           (1U << 1)
#define GSTAT_UV_CP             (1U << 2)

/* RAMPMODE values */
#define RAMPMODE_POSITION       0U  /* Position mode (using XTARGET) */
#define RAMPMODE_VELOCITY_POS   1U  /* Velocity mode, positive */
#define RAMPMODE_VELOCITY_NEG   2U  /* Velocity mode, negative */
#define RAMPMODE_HOLD           3U  /* Velocity = 0, hold position */

/* RAMPSTAT bits */
#define RAMPSTAT_POSITION_REACHED   (1U << 9)
#define RAMPSTAT_VELOCITY_REACHED   (1U << 8)
#define RAMPSTAT_VZERO              (1U << 10)
#define RAMPSTAT_STATUS_SG          (1U << 6)  /* StallGuard event */

/* DRV_STATUS bits */
#define DRVSTAT_SG_RESULT_MASK  0x3FFU          /* bits [9:0] */
#define DRVSTAT_CS_ACTUAL_SHIFT 16
#define DRVSTAT_CS_ACTUAL_MASK  (0x1FU << 16)   /* bits [20:16] */
#define DRVSTAT_STST            (1U << 31)      /* Standstill indicator */
#define DRVSTAT_OLa             (1U << 29)      /* Open load phase A */
#define DRVSTAT_OLb             (1U << 30)      /* Open load phase B */
#define DRVSTAT_S2GA            (1U << 24)      /* Short to GND phase A */
#define DRVSTAT_S2GB            (1U << 25)      /* Short to GND phase B */
#define DRVSTAT_S2VSA           (1U << 26)      /* Short to VS phase A */
#define DRVSTAT_S2VSB           (1U << 27)      /* Short to VS phase B */
#define DRVSTAT_OT              (1U << 25)      /* Overtemperature */
#define DRVSTAT_OTPW            (1U << 26)      /* Overtemp pre-warning */
#define DRVSTAT_STALLGUARD      (1U << 24)      /* StallGuard2 active */

/* DRV_STATUS fault mask (any of these = driver fault) */
#define DRVSTAT_FAULT_MASK      (DRVSTAT_S2GA | DRVSTAT_S2GB | \
                                 DRVSTAT_S2VSA | DRVSTAT_S2VSB | \
                                 DRVSTAT_OT)

/* IHOLD_IRUN packing */
#define IHOLD_IRUN(ihold, irun, iholddelay) \
    (((uint32_t)(ihold) & 0x1F) | \
     (((uint32_t)(irun) & 0x1F) << 8) | \
     (((uint32_t)(iholddelay) & 0x0F) << 16))

/* CHOPCONF defaults (SpreadCycle, 16 microsteps) */
#define CHOPCONF_DEFAULT        0x000100C3U  /* TOFF=3, HSTRT=4, HEND=1, TBL=2, MRES=16 */

/* COOLCONF StallGuard2 threshold packing */
#define COOLCONF_SGT(threshold) (((uint32_t)(threshold) & 0x7F) << 16)

/* ──────────────────────────────────────────────
 * TMC5160 Driver Instance
 * ────────────────────────────────────────────── */

/** Per-axis TMC5160 state */
typedef struct {
    uint8_t     axis;           /* axis_id_t */
    uint8_t     cs_index;       /* SPI chip-select index */
    bool        initialized;    /* Driver initialized flag */
    bool        enabled;        /* Motor outputs enabled */
    uint32_t    drv_status;     /* Cached DRV_STATUS */
    uint16_t    sg_result;      /* Cached StallGuard2 result */
    uint16_t    cs_actual;      /* Cached actual current */
    int32_t     xactual;        /* Cached XACTUAL */
} tmc5160_t;

/* ──────────────────────────────────────────────
 * Driver API
 * ────────────────────────────────────────────── */

/**
 * @brief Initialize TMC5160 driver for a specific axis
 * @param tmc Pointer to driver instance
 * @param axis axis_id_t
 * @param cs_index SPI chip-select index
 * @return true on success
 */
bool tmc5160_init(tmc5160_t *tmc, uint8_t axis, uint8_t cs_index);

/**
 * @brief Write a TMC5160 register
 * @param tmc Driver instance
 * @param reg Register address (0x00–0x7F)
 * @param value 32-bit register value
 */
void tmc5160_write_reg(tmc5160_t *tmc, uint8_t reg, uint32_t value);

/**
 * @brief Read a TMC5160 register
 * @param tmc Driver instance
 * @param reg Register address
 * @return 32-bit register value
 * @note SPI read requires two transfers (address + dummy, then read result)
 */
uint32_t tmc5160_read_reg(tmc5160_t *tmc, uint8_t reg);

/**
 * @brief Enable motor outputs (de-assert DRV_ENN for this axis)
 */
void tmc5160_enable(tmc5160_t *tmc);

/**
 * @brief Disable motor outputs (assert DRV_ENN)
 */
void tmc5160_disable(tmc5160_t *tmc);

/**
 * @brief Set motor current
 * @param tmc Driver instance
 * @param ihold Hold current (0-31)
 * @param irun Run current (0-31)
 * @param iholddelay Hold delay (0-15)
 */
void tmc5160_set_current(tmc5160_t *tmc, uint8_t ihold, uint8_t irun,
                         uint8_t iholddelay);

/**
 * @brief Set ramp parameters (velocity and acceleration)
 * @param vmax Maximum velocity (TMC internal units)
 * @param amax Maximum acceleration
 * @param dmax Maximum deceleration
 */
void tmc5160_set_ramp(tmc5160_t *tmc, uint32_t vmax, uint32_t amax,
                      uint32_t dmax);

/**
 * @brief Move to absolute position (position mode)
 * @param tmc Driver instance
 * @param position Target position in microsteps
 */
void tmc5160_move_to(tmc5160_t *tmc, int32_t position);

/**
 * @brief Start velocity mode
 * @param tmc Driver instance
 * @param velocity Signed velocity (positive = forward, negative = reverse)
 */
void tmc5160_move_velocity(tmc5160_t *tmc, int32_t velocity);

/**
 * @brief Stop motion (decelerate to zero)
 */
void tmc5160_stop(tmc5160_t *tmc);

/**
 * @brief Check if target position has been reached
 */
bool tmc5160_position_reached(tmc5160_t *tmc);

/**
 * @brief Get current actual position
 */
int32_t tmc5160_get_position(tmc5160_t *tmc);

/**
 * @brief Set current position (without moving)
 */
void tmc5160_set_position(tmc5160_t *tmc, int32_t position);

/**
 * @brief Configure StallGuard2 threshold
 * @param tmc Driver instance
 * @param threshold SGT value (signed, -64 to +63)
 */
void tmc5160_set_stallguard(tmc5160_t *tmc, int8_t threshold);

/**
 * @brief Poll DRV_STATUS and cache results
 * @param tmc Driver instance
 * @return Cached DRV_STATUS value
 * @note Updates tmc->drv_status, tmc->sg_result, tmc->cs_actual
 */
uint32_t tmc5160_poll_status(tmc5160_t *tmc);

/**
 * @brief Check if any driver fault is active
 * @return true if fault detected (overtemp, short, etc.)
 */
bool tmc5160_has_fault(const tmc5160_t *tmc);

/**
 * @brief Clear GSTAT error flags
 */
void tmc5160_clear_errors(tmc5160_t *tmc);

/**
 * @brief Configure chopper (SpreadCycle/StealthChop)
 * @param tmc Driver instance
 * @param chopconf CHOPCONF register value
 */
void tmc5160_set_chopconf(tmc5160_t *tmc, uint32_t chopconf);

/**
 * @brief Get motor HAL ops for TMC5160
 * @return Pointer to static motor_hal_ops_t vtable
 *
 * Used by motor_hal.c to bind a TMC5160 axis to the unified motor HAL
 * interface.  The returned pointer is valid for the lifetime of the program.
 */
struct motor_hal_ops;
const struct motor_hal_ops *tmc5160_get_motor_hal_ops(void);

#ifdef __cplusplus
}
#endif

#endif /* TMC5160_H */
