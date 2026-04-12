/**
 * @file tmc5130.c
 * @brief TMC5130 stepper motor driver -- SPI communication and control
 * @author ortho-bender firmware team
 *
 * SPI Protocol (TMC5130 Datasheet 4.1):
 *   Write: [0x80 | reg_addr] [data_31:24] [data_23:16] [data_15:8] [data_7:0]
 *   Read:  [reg_addr]        [0x00]       [0x00]       [0x00]      [0x00]
 *          (response arrives on the NEXT transfer)
 *
 * Implementation follows the same pattern as tmc5160.c.  The TMC5130 register
 * map is compatible for the registers used here (ramp, chopper, DRV_STATUS).
 *
 * Memory: ~48 bytes per tmc5130_t instance (static allocation).
 * No dynamic memory allocation.
 *
 * IEC 62304 SW Class: B
 */

#include "tmc5130.h"
#include "motor_hal.h"
#include "motor_config.h"
#include "hal_spi.h"
#include "hal_gpio.h"
#include "machine_config.h"

#include <stddef.h>

/* ======================================================================
 * SPI Helpers
 * ====================================================================== */

#define TMC5130_SPI_WRITE_BIT   0x80U
#define TMC5130_SPI_FRAME_LEN   5U

static void tmc5130_spi_transfer(uint8_t cs_index,
                                 const uint8_t tx[TMC5130_SPI_FRAME_LEN],
                                 uint8_t rx[TMC5130_SPI_FRAME_LEN])
{
    hal_spi_cs_assert(HAL_SPI_TMC, cs_index);
    (void)hal_spi_transfer(HAL_SPI_TMC, tx, rx, TMC5130_SPI_FRAME_LEN);
    hal_spi_cs_deassert(HAL_SPI_TMC, cs_index);
}

/* ======================================================================
 * Register Access
 * ====================================================================== */

void tmc5130_write_reg(tmc5130_t *tmc, uint8_t reg, uint32_t value)
{
    uint8_t tx[TMC5130_SPI_FRAME_LEN] = {0U};
    uint8_t rx[TMC5130_SPI_FRAME_LEN] = {0U};

    tx[0] = TMC5130_SPI_WRITE_BIT | (reg & 0x7FU);
    tx[1] = (uint8_t)((value >> 24) & 0xFFU);
    tx[2] = (uint8_t)((value >> 16) & 0xFFU);
    tx[3] = (uint8_t)((value >> 8) & 0xFFU);
    tx[4] = (uint8_t)(value & 0xFFU);

    tmc5130_spi_transfer(tmc->cs_index, tx, rx);
}

uint32_t tmc5130_read_reg(tmc5130_t *tmc, uint8_t reg)
{
    uint8_t tx[TMC5130_SPI_FRAME_LEN] = {0U};
    uint8_t rx[TMC5130_SPI_FRAME_LEN] = {0U};

    /* First transfer: send address */
    tx[0] = reg & 0x7FU;
    tmc5130_spi_transfer(tmc->cs_index, tx, rx);

    /* Second transfer: read data */
    tx[0] = reg & 0x7FU;
    tmc5130_spi_transfer(tmc->cs_index, tx, rx);

    return ((uint32_t)rx[1] << 24) |
           ((uint32_t)rx[2] << 16) |
           ((uint32_t)rx[3] << 8) |
           (uint32_t)rx[4];
}

/* ======================================================================
 * Initialization
 * ====================================================================== */

bool tmc5130_init(tmc5130_t *tmc, uint8_t axis, uint8_t cs_index)
{
    if (tmc == NULL) {
        return false;
    }

    tmc->axis        = axis;
    tmc->cs_index    = cs_index;
    tmc->initialized = false;
    tmc->enabled     = false;
    tmc->drv_status  = 0U;
    tmc->sg_result   = 0U;
    tmc->cs_actual   = 0U;
    tmc->xactual     = 0;

    /* Clear GSTAT */
    tmc5130_write_reg(tmc, TMC5130_REG_GSTAT,
                      TMC5130_GSTAT_RESET | TMC5130_GSTAT_DRV_ERR |
                      TMC5130_GSTAT_UV_CP);

    /* Verify SPI communication */
    uint32_t gstat = tmc5130_read_reg(tmc, TMC5130_REG_GSTAT);
    if (gstat == 0xFFFFFFFFU) {
        return false;
    }

    /* GCONF: multistep filter, StallGuard on DIAG0 */
    tmc5130_write_reg(tmc, TMC5130_REG_GCONF,
                      TMC5130_GCONF_MULTISTEP | TMC5130_GCONF_DIAG0_STALL);

    /* CHOPCONF: SpreadCycle, 16 microsteps */
    tmc5130_set_chopconf(tmc, TMC5130_CHOPCONF_DEFAULT);

    /* Default current */
    tmc5130_set_current(tmc, TMC5160_IHOLD_DEFAULT,
                        TMC5160_IRUN_DEFAULT,
                        TMC5160_IHOLDDELAY_DEFAULT);

    /* Default ramp */
    tmc5130_write_reg(tmc, TMC5130_REG_VSTART, 1U);
    tmc5130_write_reg(tmc, TMC5130_REG_VSTOP, 10U);
    tmc5130_write_reg(tmc, TMC5130_REG_A1, 1000U);
    tmc5130_write_reg(tmc, TMC5130_REG_V1, 50000U);
    tmc5130_write_reg(tmc, TMC5130_REG_D1, 1400U);
    tmc5130_write_reg(tmc, TMC5130_REG_TZEROWAIT, 0U);

    /* Position mode */
    tmc5130_write_reg(tmc, TMC5130_REG_RAMPMODE, TMC5130_RAMPMODE_POSITION);

    /* Set position to 0 */
    tmc5130_write_reg(tmc, TMC5130_REG_XACTUAL, 0U);
    tmc5130_write_reg(tmc, TMC5130_REG_XTARGET, 0U);

    /* TPOWERDOWN */
    tmc5130_write_reg(tmc, TMC5130_REG_TPOWERDOWN, 200U);

    tmc->initialized = true;
    return true;
}

/* ======================================================================
 * Enable / Disable
 * ====================================================================== */

void tmc5130_enable(tmc5130_t *tmc)
{
    if (tmc == NULL) {
        return;
    }
    hal_gpio_write(HAL_GPIO_DRV_ENN, false);
    tmc->enabled = true;
}

void tmc5130_disable(tmc5130_t *tmc)
{
    if (tmc == NULL) {
        return;
    }
    hal_gpio_write(HAL_GPIO_DRV_ENN, true);
    tmc->enabled = false;
}

/* ======================================================================
 * Current / Ramp / Chopper
 * ====================================================================== */

void tmc5130_set_current(tmc5130_t *tmc, uint8_t ihold, uint8_t irun,
                         uint8_t iholddelay)
{
    if (tmc == NULL) {
        return;
    }
    tmc5130_write_reg(tmc, TMC5130_REG_IHOLD_IRUN,
                      TMC5130_IHOLD_IRUN(ihold, irun, iholddelay));
}

void tmc5130_set_ramp(tmc5130_t *tmc, uint32_t vmax, uint32_t amax,
                      uint32_t dmax)
{
    if (tmc == NULL) {
        return;
    }
    tmc5130_write_reg(tmc, TMC5130_REG_VMAX, vmax);
    tmc5130_write_reg(tmc, TMC5130_REG_AMAX, amax);
    tmc5130_write_reg(tmc, TMC5130_REG_DMAX, dmax);
}

void tmc5130_set_chopconf(tmc5130_t *tmc, uint32_t chopconf)
{
    if (tmc == NULL) {
        return;
    }
    tmc5130_write_reg(tmc, TMC5130_REG_CHOPCONF, chopconf);
}

/* ======================================================================
 * Motion Commands
 * ====================================================================== */

void tmc5130_move_to(tmc5130_t *tmc, int32_t position)
{
    if (tmc == NULL) {
        return;
    }
    tmc5130_write_reg(tmc, TMC5130_REG_RAMPMODE, TMC5130_RAMPMODE_POSITION);
    tmc5130_write_reg(tmc, TMC5130_REG_XTARGET, (uint32_t)position);
}

void tmc5130_stop(tmc5130_t *tmc)
{
    if (tmc == NULL) {
        return;
    }
    tmc5130_write_reg(tmc, TMC5130_REG_VMAX, 0U);
    tmc5130_write_reg(tmc, TMC5130_REG_RAMPMODE, TMC5130_RAMPMODE_VEL_POS);
}

/* ======================================================================
 * Position
 * ====================================================================== */

bool tmc5130_position_reached(tmc5130_t *tmc)
{
    if (tmc == NULL) {
        return true;
    }
    uint32_t rampstat = tmc5130_read_reg(tmc, TMC5130_REG_RAMPSTAT);
    return (rampstat & TMC5130_RAMPSTAT_POS_REACHED) != 0U;
}

int32_t tmc5130_get_position(tmc5130_t *tmc)
{
    if (tmc == NULL) {
        return 0;
    }
    return (int32_t)tmc5130_read_reg(tmc, TMC5130_REG_XACTUAL);
}

void tmc5130_set_position(tmc5130_t *tmc, int32_t position)
{
    if (tmc == NULL) {
        return;
    }
    tmc5130_write_reg(tmc, TMC5130_REG_XACTUAL, (uint32_t)position);
    tmc5130_write_reg(tmc, TMC5130_REG_XTARGET, (uint32_t)position);
}

/* ======================================================================
 * StallGuard2
 * ====================================================================== */

void tmc5130_set_stallguard(tmc5130_t *tmc, int8_t threshold)
{
    if (tmc == NULL) {
        return;
    }
    tmc5130_write_reg(tmc, TMC5130_REG_TCOOLTHRS, 0x000FFFFFU);
    tmc5130_write_reg(tmc, TMC5130_REG_COOLCONF,
                      TMC5130_COOLCONF_SGT((uint8_t)threshold));
}

/* ======================================================================
 * Status Polling
 * ====================================================================== */

uint32_t tmc5130_poll_status(tmc5130_t *tmc)
{
    if (tmc == NULL) {
        return 0U;
    }
    tmc->drv_status = tmc5130_read_reg(tmc, TMC5130_REG_DRVSTATUS);
    tmc->sg_result = (uint16_t)(tmc->drv_status & TMC5130_DRVSTAT_SG_MASK);
    tmc->cs_actual = (uint16_t)((tmc->drv_status & TMC5130_DRVSTAT_CS_MASK)
                                >> TMC5130_DRVSTAT_CS_SHIFT);
    tmc->xactual = tmc5130_get_position(tmc);
    return tmc->drv_status;
}

bool tmc5130_has_fault(const tmc5130_t *tmc)
{
    if (tmc == NULL) {
        return true;
    }
    return (tmc->drv_status & TMC5130_DRVSTAT_FAULT_MASK) != 0U;
}

void tmc5130_clear_errors(tmc5130_t *tmc)
{
    if (tmc == NULL) {
        return;
    }
    tmc5130_write_reg(tmc, TMC5130_REG_GSTAT,
                      TMC5130_GSTAT_RESET | TMC5130_GSTAT_DRV_ERR |
                      TMC5130_GSTAT_UV_CP);
}

/* ======================================================================
 * Motor HAL Adapter
 * ====================================================================== */

static motor_result_t tmc5130_hal_init(void *drv_ctx)
{
    tmc5130_t *tmc = (tmc5130_t *)drv_ctx;
    if (tmc == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    bool ok = tmc5130_init(tmc, tmc->axis, tmc->cs_index);
    return ok ? MOTOR_OK : MOTOR_ERR_DRIVER_FAULT;
}

static motor_result_t tmc5130_hal_move_abs(void *drv_ctx, int32_t target_steps,
                                           uint32_t vmax, uint32_t amax)
{
    tmc5130_t *tmc = (tmc5130_t *)drv_ctx;
    if (tmc == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    tmc5130_set_ramp(tmc, vmax, amax, amax);
    tmc5130_move_to(tmc, target_steps);
    return MOTOR_OK;
}

static bool tmc5130_hal_position_reached(void *drv_ctx)
{
    return tmc5130_position_reached((tmc5130_t *)drv_ctx);
}

static int32_t tmc5130_hal_get_position(void *drv_ctx)
{
    return tmc5130_get_position((tmc5130_t *)drv_ctx);
}

static void tmc5130_hal_emergency_stop(void *drv_ctx)
{
    tmc5130_t *tmc = (tmc5130_t *)drv_ctx;
    if (tmc != NULL) {
        tmc5130_stop(tmc);
        hal_gpio_write(HAL_GPIO_DRV_ENN, true);
    }
}

static motor_result_t tmc5130_hal_poll_status(void *drv_ctx,
                                              motor_status_t *out)
{
    tmc5130_t *tmc = (tmc5130_t *)drv_ctx;
    if ((tmc == NULL) || (out == NULL)) {
        return MOTOR_ERR_INVALID_PARAM;
    }

    uint32_t ds = tmc5130_poll_status(tmc);

    out->ot        = (uint8_t)((ds & TMC5130_DRVSTAT_OT) != 0U);
    out->otpw      = (uint8_t)((ds & TMC5130_DRVSTAT_OTPW) != 0U);
    out->s2ga      = (uint8_t)((ds & TMC5130_DRVSTAT_S2GA) != 0U);
    out->s2gb      = (uint8_t)((ds & TMC5130_DRVSTAT_S2GB) != 0U);
    out->ola       = (uint8_t)((ds & TMC5130_DRVSTAT_OLA) != 0U);
    out->olb       = (uint8_t)((ds & TMC5130_DRVSTAT_OLB) != 0U);
    out->stall     = 0U;
    out->sg_result = (int16_t)tmc->sg_result;

    /* Check RAMPSTAT for StallGuard event */
    uint32_t rs = tmc5130_read_reg(tmc, TMC5130_REG_RAMPSTAT);
    if ((rs & TMC5130_RAMPSTAT_SG) != 0U) {
        out->stall = 1U;
    }

    if (tmc5130_has_fault(tmc)) {
        if ((ds & TMC5130_DRVSTAT_OT) != 0U) {
            return MOTOR_ERR_OVERTEMP;
        }
        return MOTOR_ERR_SHORT;
    }

    return MOTOR_OK;
}

static void tmc5130_hal_enable(void *drv_ctx)
{
    tmc5130_enable((tmc5130_t *)drv_ctx);
}

static void tmc5130_hal_disable(void *drv_ctx)
{
    tmc5130_disable((tmc5130_t *)drv_ctx);
}

static const motor_hal_ops_t s_tmc5130_ops = {
    .init             = tmc5130_hal_init,
    .move_abs         = tmc5130_hal_move_abs,
    .position_reached = tmc5130_hal_position_reached,
    .get_position     = tmc5130_hal_get_position,
    .emergency_stop   = tmc5130_hal_emergency_stop,
    .poll_status      = tmc5130_hal_poll_status,
    .enable           = tmc5130_hal_enable,
    .disable          = tmc5130_hal_disable,
};

const motor_hal_ops_t *tmc5130_get_motor_hal_ops(void)
{
    return &s_tmc5130_ops;
}
