/**
 * @file tmc260c.h
 * @brief TMC260C-PA stepper motor driver -- SPI configuration and diagnostics
 * @author ortho-bender firmware team
 *
 * The TMC260C-PA is a STEP/DIR stepper driver with SPI-configurable chopper,
 * current, microstepping, and StallGuard2 diagnostics.  Unlike the TMC5160
 * there is no internal ramp generator; the host MCU generates STEP pulses
 * directly via GPT timers (see step_gen.h).
 *
 * SPI protocol: 20-bit datagrams (MSB first, SPI Mode 3).
 * Each write simultaneously returns a 20-bit status/SG response.
 *
 * Reference: TMC260C-PA Datasheet Rev 1.04 (Trinamic / ADI)
 *
 * IEC 62304 SW Class: B
 */

#ifndef TMC260C_H
#define TMC260C_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ======================================================================
 * TMC260C-PA Register Address Tags  (bits [19:17] of the 20-bit word)
 * ====================================================================== */

/** Write registers -- address tag in upper 3 bits */
#define TMC260C_REG_DRVCTRL_STEP    0x00U   /**< DRVCTRL  (STEP/DIR mode, bit19=0, bit18=0) */
#define TMC260C_REG_CHOPCONF        0x04U   /**< CHOPCONF (bits [19:17] = 100)               */
#define TMC260C_REG_SMARTEN         0x05U   /**< SMARTEN  (bits [19:17] = 101)               */
#define TMC260C_REG_SGCSCONF        0x06U   /**< SGCSCONF (bits [19:17] = 110)               */
#define TMC260C_REG_DRVCONF         0x07U   /**< DRVCONF  (bits [19:17] = 111)               */

/* ======================================================================
 * DRVCTRL (STEP/DIR mode) -- bits [19:18] = 00
 * ====================================================================== */

/** Microstepping resolution encoding (bits [3:0] of DRVCTRL) */
typedef enum {
    TMC260C_MRES_256    = 0x00U,    /**< 256 microsteps */
    TMC260C_MRES_128    = 0x01U,    /**< 128 microsteps */
    TMC260C_MRES_64     = 0x02U,    /**<  64 microsteps */
    TMC260C_MRES_32     = 0x03U,    /**<  32 microsteps */
    TMC260C_MRES_16     = 0x04U,    /**<  16 microsteps */
    TMC260C_MRES_8      = 0x05U,    /**<   8 microsteps */
    TMC260C_MRES_4      = 0x06U,    /**<   4 microsteps */
    TMC260C_MRES_2      = 0x07U,    /**<   2 microsteps (half step) */
    TMC260C_MRES_1      = 0x08U,    /**<   1 microstep  (full step) */
} tmc260c_mres_t;

/* DRVCTRL flags */
#define TMC260C_DRVCTRL_DEDGE       (1U << 8)   /**< Enable double edge STEP pulses */
#define TMC260C_DRVCTRL_INTPOL      (1U << 9)   /**< Enable 256 microstep interpolation */

/* ======================================================================
 * CHOPCONF -- bits [19:17] = 100
 * ====================================================================== */

#define TMC260C_CHOPCONF_TAG        (0x04U << 17)

/* CHOPCONF fields */
#define TMC260C_CHOPCONF_TOFF_SHIFT     0U
#define TMC260C_CHOPCONF_TOFF_MASK      0x0FU
#define TMC260C_CHOPCONF_HSTRT_SHIFT    4U
#define TMC260C_CHOPCONF_HSTRT_MASK     0x07U
#define TMC260C_CHOPCONF_HEND_SHIFT     7U
#define TMC260C_CHOPCONF_HEND_MASK      0x0FU
#define TMC260C_CHOPCONF_HDEC_SHIFT     11U
#define TMC260C_CHOPCONF_HDEC_MASK      0x03U
#define TMC260C_CHOPCONF_RNDTF          (1U << 13)  /**< Random TOFF time */
#define TMC260C_CHOPCONF_CHM            (1U << 14)  /**< Chopper mode: 0=SpreadCycle */
#define TMC260C_CHOPCONF_TBL_SHIFT      15U
#define TMC260C_CHOPCONF_TBL_MASK       0x03U

/** Default CHOPCONF: SpreadCycle, TOFF=5, HSTRT=4, HEND=1, TBL=2 */
#define TMC260C_CHOPCONF_DEFAULT \
    (TMC260C_CHOPCONF_TAG | \
     (5U  << TMC260C_CHOPCONF_TOFF_SHIFT) | \
     (4U  << TMC260C_CHOPCONF_HSTRT_SHIFT) | \
     (1U  << TMC260C_CHOPCONF_HEND_SHIFT) | \
     (2U  << TMC260C_CHOPCONF_TBL_SHIFT))

/* ======================================================================
 * SMARTEN (coolStep) -- bits [19:17] = 101
 * ====================================================================== */

#define TMC260C_SMARTEN_TAG         (0x05U << 17)

#define TMC260C_SMARTEN_SEMIN_SHIFT     0U
#define TMC260C_SMARTEN_SEMIN_MASK      0x0FU
#define TMC260C_SMARTEN_SEUP_SHIFT      5U
#define TMC260C_SMARTEN_SEUP_MASK       0x03U
#define TMC260C_SMARTEN_SEMAX_SHIFT     8U
#define TMC260C_SMARTEN_SEMAX_MASK      0x0FU
#define TMC260C_SMARTEN_SEDN_SHIFT      13U
#define TMC260C_SMARTEN_SEDN_MASK       0x03U
#define TMC260C_SMARTEN_SEIMIN          (1U << 15)

/** Default SMARTEN: coolStep disabled (SEMIN=0) */
#define TMC260C_SMARTEN_DEFAULT     (TMC260C_SMARTEN_TAG)

/* ======================================================================
 * SGCSCONF (StallGuard2 + current scale) -- bits [19:17] = 110
 * ====================================================================== */

#define TMC260C_SGCSCONF_TAG        (0x06U << 17)

#define TMC260C_SGCSCONF_CS_SHIFT       0U      /**< Current scale bits [4:0] */
#define TMC260C_SGCSCONF_CS_MASK        0x1FU
#define TMC260C_SGCSCONF_SGT_SHIFT      8U      /**< StallGuard2 threshold [6:0] signed */
#define TMC260C_SGCSCONF_SGT_MASK       0x7FU
#define TMC260C_SGCSCONF_SFILT          (1U << 16)  /**< StallGuard2 filter enable */

/* ======================================================================
 * DRVCONF -- bits [19:17] = 111
 * ====================================================================== */

#define TMC260C_DRVCONF_TAG         (0x07U << 17)

#define TMC260C_DRVCONF_RDSEL_SHIFT     4U      /**< Read selection */
#define TMC260C_DRVCONF_RDSEL_MASK      0x03U
#define TMC260C_DRVCONF_VSENSE          (1U << 6)   /**< High sensitivity current sense */
#define TMC260C_DRVCONF_SDOFF           (1U << 7)   /**< STEP/DIR disable (SPI mode) */
#define TMC260C_DRVCONF_TS2G_SHIFT      8U
#define TMC260C_DRVCONF_TS2G_MASK       0x03U
#define TMC260C_DRVCONF_DISS2G          (1U << 10)  /**< Disable S2G detection */
#define TMC260C_DRVCONF_SLPL_SHIFT      12U
#define TMC260C_DRVCONF_SLPL_MASK       0x03U
#define TMC260C_DRVCONF_SLPH_SHIFT      14U
#define TMC260C_DRVCONF_SLPH_MASK       0x03U
#define TMC260C_DRVCONF_TST             (1U << 16)  /**< Test mode (do not set) */

/** RDSEL values for status response */
typedef enum {
    TMC260C_RDSEL_MICROSTEP     = 0U,   /**< Response = microstep counter */
    TMC260C_RDSEL_STALLGUARD    = 1U,   /**< Response = StallGuard2 value */
    TMC260C_RDSEL_COOLSTEP      = 2U,   /**< Response = coolStep & SG */
} tmc260c_rdsel_t;

/** Default DRVCONF: STEP/DIR mode, read StallGuard2, high sense resistor */
#define TMC260C_DRVCONF_DEFAULT \
    (TMC260C_DRVCONF_TAG | \
     ((uint32_t)TMC260C_RDSEL_STALLGUARD << TMC260C_DRVCONF_RDSEL_SHIFT) | \
     TMC260C_DRVCONF_VSENSE)

/* ======================================================================
 * SPI Response (20-bit read-back)
 * ====================================================================== */

/** Status flags in response bits [19:18] and fault bits */
#define TMC260C_RESP_SG             (1U << 0)    /**< StallGuard2 active */
#define TMC260C_RESP_OT             (1U << 1)    /**< Overtemperature shutdown */
#define TMC260C_RESP_OTPW           (1U << 2)    /**< Overtemperature pre-warning */
#define TMC260C_RESP_S2GA           (1U << 3)    /**< Short to GND phase A */
#define TMC260C_RESP_S2GB           (1U << 4)    /**< Short to GND phase B */
#define TMC260C_RESP_OLA            (1U << 5)    /**< Open load phase A */
#define TMC260C_RESP_OLB            (1U << 6)    /**< Open load phase B */
#define TMC260C_RESP_STST           (1U << 7)    /**< Standstill indicator */

/** Fault mask (any of these bits = driver fault) */
#define TMC260C_RESP_FAULT_MASK \
    (TMC260C_RESP_OT | TMC260C_RESP_S2GA | TMC260C_RESP_S2GB)

/** StallGuard2 value extraction (RDSEL = SG mode, bits [19:10]) */
#define TMC260C_RESP_SG_VALUE_SHIFT     10U
#define TMC260C_RESP_SG_VALUE_MASK      0x3FFU

/* ======================================================================
 * TMC260C Driver Instance
 * ====================================================================== */

/** Per-axis TMC260C-PA state */
typedef struct {
    uint8_t     axis;           /**< axis_id_t */
    uint8_t     cs_index;       /**< SPI chip-select index (hal_gpio pin) */
    bool        initialized;    /**< Driver initialized flag */
    uint32_t    last_response;  /**< Last 20-bit SPI response */
    uint16_t    sg_result;      /**< Cached StallGuard2 result (0--1023) */
    uint8_t     status_flags;   /**< Cached status flags (bits [7:0] of response) */
    uint8_t     current_scale;  /**< Current scale setting (0--31) */
    tmc260c_mres_t  microstep;  /**< Current microstepping resolution */
} tmc260c_t;

/* ======================================================================
 * Driver API
 * ====================================================================== */

/**
 * @brief Initialize TMC260C-PA driver for a specific axis
 * @param tmc   Pointer to driver instance (caller-allocated, static)
 * @param axis  axis_id_t (AXIS_FEED, AXIS_BEND, ...)
 * @param cs_index  Chip-select GPIO index for this axis
 * @return true on success, false if SPI init fails
 *
 * Configures DRVCONF, CHOPCONF, SGCSCONF, SMARTEN, DRVCTRL with defaults.
 * Motor current set to TMC260C_IRUN_DEFAULT.  Microstepping set to 16x.
 */
bool tmc260c_init(tmc260c_t *tmc, uint8_t axis, uint8_t cs_index);

/**
 * @brief Write a 20-bit datagram to TMC260C-PA and read response
 * @param tmc   Driver instance
 * @param data  20-bit datagram (upper 12 bits of uint32_t are ignored)
 * @return 20-bit response (status + SG/microstep/coolStep depending on RDSEL)
 *
 * SPI transfer: 3 bytes, MSB first, SPI Mode 3, max 2 MHz for TMC260C-PA.
 */
uint32_t tmc260c_spi_transfer(tmc260c_t *tmc, uint32_t data);

/**
 * @brief Set motor run current
 * @param tmc   Driver instance
 * @param scale Current scale (0--31).  Actual current = (scale+1)/32 * Vfs/Rsense
 *
 * For 0.22 ohm sense resistor + VSENSE=1:  I_rms = (scale+1)/32 * 0.165/0.22
 * Scale 20 ~ 0.47A, Scale 31 ~ 0.73A per coil (x sqrt(2) for peak).
 */
void tmc260c_set_current(tmc260c_t *tmc, uint8_t scale);

/**
 * @brief Set microstepping resolution
 * @param tmc   Driver instance
 * @param mres  Microstepping resolution enum
 */
void tmc260c_set_microstep(tmc260c_t *tmc, tmc260c_mres_t mres);

/**
 * @brief Configure StallGuard2 threshold
 * @param tmc       Driver instance
 * @param threshold Signed threshold (-64 to +63).  Higher = less sensitive.
 * @param filter    Enable StallGuard2 digital filter (recommended)
 */
void tmc260c_set_stallguard(tmc260c_t *tmc, int8_t threshold, bool filter);

/**
 * @brief Read driver status (poll via SPI -- sends DRVCONF read)
 * @param tmc   Driver instance
 * @return Raw 20-bit response with status flags and SG value
 *
 * Updates tmc->status_flags, tmc->sg_result, tmc->last_response.
 * Must be called periodically (200 Hz recommended) for fault detection.
 */
uint32_t tmc260c_read_status(tmc260c_t *tmc);

/**
 * @brief Get cached StallGuard2 value
 * @param tmc   Driver instance
 * @return StallGuard2 result (0--1023), updated by tmc260c_read_status()
 */
uint16_t tmc260c_get_sg_value(const tmc260c_t *tmc);

/**
 * @brief Check if any driver fault is active
 * @param tmc   Driver instance
 * @return true if overtemp or short-to-ground detected
 */
bool tmc260c_has_fault(const tmc260c_t *tmc);

/**
 * @brief Configure chopper parameters
 * @param tmc       Driver instance
 * @param chopconf  Raw CHOPCONF register value (including tag bits)
 */
void tmc260c_set_chopconf(tmc260c_t *tmc, uint32_t chopconf);

/**
 * @brief Configure driver settings
 * @param tmc       Driver instance
 * @param drvconf   Raw DRVCONF register value (including tag bits)
 */
void tmc260c_set_drvconf(tmc260c_t *tmc, uint32_t drvconf);

/**
 * @brief Get motor HAL ops for TMC260C-PA (STEP/DIR mode)
 * @return Pointer to static motor_hal_ops_t vtable
 *
 * The TMC260C-PA adapter delegates motion to step_gen.c for pulse generation
 * and reads diagnostic status via SPI.  The caller must set the axis field
 * in tmc260c_t before binding to motor_hal.
 */
struct motor_hal_ops;
const struct motor_hal_ops *tmc260c_get_motor_hal_ops(void);

#ifdef __cplusplus
}
#endif

#endif /* TMC260C_H */
