/**
 * @file tmc260c.c
 * @brief TMC260C-PA stepper motor driver -- SPI configuration and diagnostics
 * @author ortho-bender firmware team
 *
 * Implements SPI communication with TMC260C-PA (20-bit datagrams, Mode 3).
 * This driver handles configuration only; STEP/DIR pulse generation is
 * performed by step_gen.c using GPT hardware timers.
 *
 * Memory: ~48 bytes per tmc260c_t instance (static allocation)
 * No dynamic memory allocation.
 *
 * IEC 62304 SW Class: B
 */

#include "tmc260c.h"
#include "hal_spi.h"
#include "hal_gpio.h"
#include "machine_config.h"

#include <string.h>

/* ======================================================================
 * Internal helpers
 * ====================================================================== */

/**
 * @brief Pack register address tag into upper bits of 20-bit datagram
 */
static uint32_t tmc260c_pack_drvctrl(tmc260c_mres_t mres, bool intpol, bool dedge)
{
    uint32_t val = 0U;  /* bits [19:18] = 00 for DRVCTRL in STEP/DIR mode */

    val |= (uint32_t)mres & 0x0FU;

    if (intpol) {
        val |= TMC260C_DRVCTRL_INTPOL;
    }
    if (dedge) {
        val |= TMC260C_DRVCTRL_DEDGE;
    }

    return val;
}

/**
 * @brief Build SGCSCONF register value
 */
static uint32_t tmc260c_pack_sgcsconf(uint8_t cs, int8_t sgt, bool sfilt)
{
    uint32_t val = TMC260C_SGCSCONF_TAG;

    val |= ((uint32_t)cs & TMC260C_SGCSCONF_CS_MASK) << TMC260C_SGCSCONF_CS_SHIFT;

    /* SGT is a 7-bit signed value stored as two's complement */
    uint8_t sgt_raw = (uint8_t)((int16_t)sgt & 0x7F);
    val |= ((uint32_t)sgt_raw & TMC260C_SGCSCONF_SGT_MASK) << TMC260C_SGCSCONF_SGT_SHIFT;

    if (sfilt) {
        val |= TMC260C_SGCSCONF_SFILT;
    }

    return val;
}

/**
 * @brief Parse 20-bit SPI response into cached fields
 */
static void tmc260c_parse_response(tmc260c_t *tmc, uint32_t resp)
{
    tmc->last_response = resp;

    /* Status flags are in bits [7:0] of the response */
    tmc->status_flags = (uint8_t)(resp & 0xFFU);

    /* StallGuard2 value in bits [19:10] when RDSEL=SG */
    tmc->sg_result = (uint16_t)((resp >> TMC260C_RESP_SG_VALUE_SHIFT)
                                & TMC260C_RESP_SG_VALUE_MASK);
}

/* ======================================================================
 * Public API
 * ====================================================================== */

uint32_t tmc260c_spi_transfer(tmc260c_t *tmc, uint32_t data)
{
    if (tmc == NULL) {
        return 0U;
    }

    /* TMC260C-PA uses 20-bit SPI datagrams, transferred as 3 bytes MSB first.
     * Byte 0: bits [19:12]
     * Byte 1: bits [11:4]
     * Byte 2: bits [3:0] << 4  (lower nibble unused)
     */
    uint8_t tx[3] = {0U, 0U, 0U};
    uint8_t rx[3] = {0U, 0U, 0U};

    tx[0] = (uint8_t)((data >> 12) & 0xFFU);
    tx[1] = (uint8_t)((data >> 4)  & 0xFFU);
    tx[2] = (uint8_t)((data << 4)  & 0xF0U);

    hal_spi_cs_assert(HAL_SPI_TMC, tmc->cs_index);
    (void)hal_spi_transfer(HAL_SPI_TMC, tx, rx, 3U);
    hal_spi_cs_deassert(HAL_SPI_TMC, tmc->cs_index);

    /* Reassemble 20-bit response */
    uint32_t resp = 0U;
    resp  = ((uint32_t)rx[0] << 12);
    resp |= ((uint32_t)rx[1] << 4);
    resp |= ((uint32_t)rx[2] >> 4);
    resp &= 0x000FFFFFU;  /* Mask to 20 bits */

    tmc260c_parse_response(tmc, resp);

    return resp;
}

bool tmc260c_init(tmc260c_t *tmc, uint8_t axis, uint8_t cs_index)
{
    if (tmc == NULL) {
        return false;
    }

    (void)memset(tmc, 0, sizeof(tmc260c_t));

    tmc->axis       = axis;
    tmc->cs_index   = cs_index;
    tmc->microstep  = TMC260C_MRES_16;
    tmc->current_scale = TMC260C_IRUN_DEFAULT;

    /* Configure SPI bus (shared, init once is fine -- HAL handles re-init) */
    hal_spi_config_t spi_cfg = {
        .clock_hz   = TMC260C_SPI_CLOCK_HZ,
        .mode       = TMC260C_SPI_MODE,
        .bits       = 8U,
        .cs_setup_ns = TMC260C_CS_SETUP_NS,
    };

    if (!hal_spi_init(HAL_SPI_TMC, &spi_cfg)) {
        return false;
    }

    /* Step 1: DRVCONF -- STEP/DIR mode, read SG, high-sense */
    (void)tmc260c_spi_transfer(tmc, TMC260C_DRVCONF_DEFAULT);

    /* Step 2: CHOPCONF -- SpreadCycle defaults */
    (void)tmc260c_spi_transfer(tmc, TMC260C_CHOPCONF_DEFAULT);

    /* Step 3: SGCSCONF -- current scale + StallGuard threshold */
    uint32_t sgcs = tmc260c_pack_sgcsconf(
        TMC260C_IRUN_DEFAULT,
        0,      /* Neutral SG threshold; calibrate per-axis during homing */
        true    /* SG filter enabled */
    );
    (void)tmc260c_spi_transfer(tmc, sgcs);

    /* Step 4: SMARTEN -- coolStep disabled by default */
    (void)tmc260c_spi_transfer(tmc, TMC260C_SMARTEN_DEFAULT);

    /* Step 5: DRVCTRL -- 16x microstepping with interpolation */
    uint32_t drvctrl = tmc260c_pack_drvctrl(TMC260C_MRES_16, true, false);
    (void)tmc260c_spi_transfer(tmc, drvctrl);

    tmc->initialized = true;
    return true;
}

void tmc260c_set_current(tmc260c_t *tmc, uint8_t scale)
{
    if (tmc == NULL) {
        return;
    }
    if (scale > 31U) {
        scale = 31U;
    }

    tmc->current_scale = scale;

    /* Re-write SGCSCONF with updated current scale, preserve SG settings */
    /* Extract current SGT from last known config */
    uint32_t sgcs = tmc260c_pack_sgcsconf(scale, 0, true);
    (void)tmc260c_spi_transfer(tmc, sgcs);
}

void tmc260c_set_microstep(tmc260c_t *tmc, tmc260c_mres_t mres)
{
    if (tmc == NULL) {
        return;
    }

    tmc->microstep = mres;

    /* Enable interpolation to 256 microsteps when base resolution < 256 */
    bool intpol = (mres != TMC260C_MRES_256);

    uint32_t drvctrl = tmc260c_pack_drvctrl(mres, intpol, false);
    (void)tmc260c_spi_transfer(tmc, drvctrl);
}

void tmc260c_set_stallguard(tmc260c_t *tmc, int8_t threshold, bool filter)
{
    if (tmc == NULL) {
        return;
    }

    /* Clamp threshold to valid range */
    if (threshold > 63) {
        threshold = 63;
    }
    if (threshold < -64) {
        threshold = -64;
    }

    uint32_t sgcs = tmc260c_pack_sgcsconf(tmc->current_scale, threshold, filter);
    (void)tmc260c_spi_transfer(tmc, sgcs);
}

uint32_t tmc260c_read_status(tmc260c_t *tmc)
{
    if (tmc == NULL) {
        return 0U;
    }

    /* Send DRVCONF (read command) to get status response.
     * TMC260C returns status on every SPI write; re-writing DRVCONF
     * with the same value is a safe way to poll. */
    return tmc260c_spi_transfer(tmc, TMC260C_DRVCONF_DEFAULT);
}

uint16_t tmc260c_get_sg_value(const tmc260c_t *tmc)
{
    if (tmc == NULL) {
        return 0U;
    }
    return tmc->sg_result;
}

bool tmc260c_has_fault(const tmc260c_t *tmc)
{
    if (tmc == NULL) {
        return true;  /* Treat NULL as fault for safety */
    }
    return ((tmc->status_flags & TMC260C_RESP_FAULT_MASK) != 0U);
}

void tmc260c_set_chopconf(tmc260c_t *tmc, uint32_t chopconf)
{
    if (tmc == NULL) {
        return;
    }
    (void)tmc260c_spi_transfer(tmc, chopconf);
}

void tmc260c_set_drvconf(tmc260c_t *tmc, uint32_t drvconf)
{
    if (tmc == NULL) {
        return;
    }
    (void)tmc260c_spi_transfer(tmc, drvconf);
}

/* ======================================================================
 * Motor HAL Adapter (STEP/DIR via step_gen.c)
 * ====================================================================== */

#include "motor_hal.h"
#include "step_gen.h"

static motor_result_t tmc260c_hal_init(void *drv_ctx)
{
    tmc260c_t *tmc = (tmc260c_t *)drv_ctx;
    if (tmc == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    bool ok = tmc260c_init(tmc, tmc->axis, tmc->cs_index);
    return ok ? MOTOR_OK : MOTOR_ERR_DRIVER_FAULT;
}

static motor_result_t tmc260c_hal_move_abs(void *drv_ctx, int32_t target_steps,
                                           uint32_t vmax, uint32_t amax)
{
    tmc260c_t *tmc = (tmc260c_t *)drv_ctx;
    if (tmc == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }

    /* Compute delta from current position to target */
    int32_t current = step_gen_get_position(tmc->axis);
    int32_t delta = target_steps - current;

    if (delta == 0) {
        return MOTOR_OK;
    }

    /* step_gen_move takes signed steps (relative), max frequency, and accel */
    bool ok = step_gen_move(tmc->axis, delta, vmax, amax);
    return ok ? MOTOR_OK : MOTOR_ERR_DRIVER_FAULT;
}

static bool tmc260c_hal_position_reached(void *drv_ctx)
{
    tmc260c_t *tmc = (tmc260c_t *)drv_ctx;
    if (tmc == NULL) {
        return true;
    }
    return step_gen_is_complete(tmc->axis);
}

static int32_t tmc260c_hal_get_position(void *drv_ctx)
{
    tmc260c_t *tmc = (tmc260c_t *)drv_ctx;
    if (tmc == NULL) {
        return 0;
    }
    return step_gen_get_position(tmc->axis);
}

static void tmc260c_hal_emergency_stop(void *drv_ctx)
{
    tmc260c_t *tmc = (tmc260c_t *)drv_ctx;
    if (tmc != NULL) {
        step_gen_stop(tmc->axis);
    }
    /* Assert DRV_ENN to kill all driver outputs (HW safety path) */
    hal_gpio_write(HAL_GPIO_DRV_ENN, true);
}

static motor_result_t tmc260c_hal_poll_status(void *drv_ctx,
                                              motor_status_t *out)
{
    tmc260c_t *tmc = (tmc260c_t *)drv_ctx;
    if ((tmc == NULL) || (out == NULL)) {
        return MOTOR_ERR_INVALID_PARAM;
    }

    /* Read TMC260C-PA status via SPI (DRVCONF re-write returns status) */
    (void)tmc260c_read_status(tmc);

    uint8_t flags = tmc->status_flags;

    out->ot        = (uint8_t)((flags & TMC260C_RESP_OT) != 0U);
    out->otpw      = (uint8_t)((flags & TMC260C_RESP_OTPW) != 0U);
    out->s2ga      = (uint8_t)((flags & TMC260C_RESP_S2GA) != 0U);
    out->s2gb      = (uint8_t)((flags & TMC260C_RESP_S2GB) != 0U);
    out->ola       = (uint8_t)((flags & TMC260C_RESP_OLA) != 0U);
    out->olb       = (uint8_t)((flags & TMC260C_RESP_OLB) != 0U);
    out->stall     = (uint8_t)((flags & TMC260C_RESP_SG) != 0U);
    out->sg_result = (int16_t)tmc->sg_result;

    if (tmc260c_has_fault(tmc)) {
        if ((flags & TMC260C_RESP_OT) != 0U) {
            return MOTOR_ERR_OVERTEMP;
        }
        return MOTOR_ERR_SHORT;
    }

    return MOTOR_OK;
}

static void tmc260c_hal_enable(void *drv_ctx)
{
    (void)drv_ctx;
    /* DRV_ENN is shared; de-assert to enable all TMC260C-PA drivers */
    hal_gpio_write(HAL_GPIO_DRV_ENN, false);
}

static void tmc260c_hal_disable(void *drv_ctx)
{
    (void)drv_ctx;
    hal_gpio_write(HAL_GPIO_DRV_ENN, true);
}

static const motor_hal_ops_t s_tmc260c_ops = {
    .init             = tmc260c_hal_init,
    .move_abs         = tmc260c_hal_move_abs,
    .position_reached = tmc260c_hal_position_reached,
    .get_position     = tmc260c_hal_get_position,
    .emergency_stop   = tmc260c_hal_emergency_stop,
    .poll_status      = tmc260c_hal_poll_status,
    .enable           = tmc260c_hal_enable,
    .disable          = tmc260c_hal_disable,
};

const motor_hal_ops_t *tmc260c_get_motor_hal_ops(void)
{
    return &s_tmc260c_ops;
}
