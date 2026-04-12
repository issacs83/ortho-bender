/**
 * @file tmc5160.c
 * @brief TMC5160 stepper motor driver — SPI communication and control
 *
 * SPI Protocol (TMC5160 Datasheet 4.1):
 *   Write: [0x80 | reg_addr] [data_31:24] [data_23:16] [data_15:8] [data_7:0]
 *   Read:  [reg_addr]        [0x00]       [0x00]       [0x00]      [0x00]
 *          (response arrives on the NEXT transfer)
 *
 * IEC 62304 SW Class: B
 */

#include "tmc5160.h"
#include "hal_spi.h"
#include "hal_gpio.h"
#include "machine_config.h"
#include "motor_config.h"

#include <stddef.h>

/* ──────────────────────────────────────────────
 * SPI Helpers
 * ────────────────────────────────────────────── */

#define TMC_SPI_WRITE_BIT   0x80U
#define TMC_SPI_FRAME_LEN   5U

static void tmc_spi_transfer(uint8_t cs_index,
                             const uint8_t tx[TMC_SPI_FRAME_LEN],
                             uint8_t rx[TMC_SPI_FRAME_LEN])
{
    hal_spi_cs_assert(HAL_SPI_TMC, cs_index);
    hal_spi_transfer(HAL_SPI_TMC, tx, rx, TMC_SPI_FRAME_LEN);
    hal_spi_cs_deassert(HAL_SPI_TMC, cs_index);
}

/* ──────────────────────────────────────────────
 * Register Access
 * ────────────────────────────────────────────── */

void tmc5160_write_reg(tmc5160_t *tmc, uint8_t reg, uint32_t value)
{
    uint8_t tx[TMC_SPI_FRAME_LEN];
    uint8_t rx[TMC_SPI_FRAME_LEN];

    tx[0] = TMC_SPI_WRITE_BIT | (reg & 0x7F);
    tx[1] = (value >> 24) & 0xFF;
    tx[2] = (value >> 16) & 0xFF;
    tx[3] = (value >> 8) & 0xFF;
    tx[4] = value & 0xFF;

    tmc_spi_transfer(tmc->cs_index, tx, rx);
}

uint32_t tmc5160_read_reg(tmc5160_t *tmc, uint8_t reg)
{
    uint8_t tx[TMC_SPI_FRAME_LEN] = {0};
    uint8_t rx[TMC_SPI_FRAME_LEN] = {0};

    /* First transfer: send register address (response is previous data) */
    tx[0] = reg & 0x7F;
    tmc_spi_transfer(tmc->cs_index, tx, rx);

    /* Second transfer: read actual data */
    tx[0] = reg & 0x7F;
    tmc_spi_transfer(tmc->cs_index, tx, rx);

    return ((uint32_t)rx[1] << 24) |
           ((uint32_t)rx[2] << 16) |
           ((uint32_t)rx[3] << 8) |
           (uint32_t)rx[4];
}

/* ──────────────────────────────────────────────
 * Initialization
 * ────────────────────────────────────────────── */

bool tmc5160_init(tmc5160_t *tmc, uint8_t axis, uint8_t cs_index)
{
    tmc->axis = axis;
    tmc->cs_index = cs_index;
    tmc->initialized = false;
    tmc->enabled = false;
    tmc->drv_status = 0;
    tmc->sg_result = 0;
    tmc->cs_actual = 0;
    tmc->xactual = 0;

    /* Clear GSTAT */
    tmc5160_write_reg(tmc, TMC_REG_GSTAT,
                      GSTAT_RESET | GSTAT_DRV_ERR | GSTAT_UV_CP);

    /* Read GSTAT to verify SPI communication */
    uint32_t gstat = tmc5160_read_reg(tmc, TMC_REG_GSTAT);
    if (gstat == 0xFFFFFFFF) {
        /* SPI not responding — no chip present or wiring error */
        return false;
    }

    /* GCONF: enable StallGuard output on DIAG0, multistep filter */
    tmc5160_write_reg(tmc, TMC_REG_GCONF,
                      GCONF_MULTISTEP_FILT | GCONF_DIAG0_STALL);

    /* CHOPCONF: SpreadCycle, 16 microsteps */
    tmc5160_set_chopconf(tmc, CHOPCONF_DEFAULT);

    /* Set default current */
    tmc5160_set_current(tmc, TMC5160_IHOLD_DEFAULT,
                        TMC5160_IRUN_DEFAULT,
                        TMC5160_IHOLDDELAY_DEFAULT);

    /* Set default ramp */
    tmc5160_write_reg(tmc, TMC_REG_VSTART, 1);
    tmc5160_write_reg(tmc, TMC_REG_VSTOP, 10);
    tmc5160_write_reg(tmc, TMC_REG_A1, 1000);
    tmc5160_write_reg(tmc, TMC_REG_V1, 50000);
    tmc5160_write_reg(tmc, TMC_REG_D1, 1400);
    tmc5160_write_reg(tmc, TMC_REG_TZEROWAIT, 0);

    /* Position mode */
    tmc5160_write_reg(tmc, TMC_REG_RAMPMODE, RAMPMODE_POSITION);

    /* Set position to 0 */
    tmc5160_write_reg(tmc, TMC_REG_XACTUAL, 0);
    tmc5160_write_reg(tmc, TMC_REG_XTARGET, 0);

    /* TPOWERDOWN: power down after 2 seconds standstill */
    tmc5160_write_reg(tmc, TMC_REG_TPOWERDOWN, 200);

    tmc->initialized = true;
    return true;
}

/* ──────────────────────────────────────────────
 * Enable / Disable
 * ────────────────────────────────────────────── */

void tmc5160_enable(tmc5160_t *tmc)
{
    /* DRV_ENN is shared — de-assert (active-low means HIGH = enabled) */
    hal_gpio_write(HAL_GPIO_DRV_ENN, false);
    tmc->enabled = true;
}

void tmc5160_disable(tmc5160_t *tmc)
{
    hal_gpio_write(HAL_GPIO_DRV_ENN, true);
    tmc->enabled = false;
}

/* ──────────────────────────────────────────────
 * Current Control
 * ────────────────────────────────────────────── */

void tmc5160_set_current(tmc5160_t *tmc, uint8_t ihold, uint8_t irun,
                         uint8_t iholddelay)
{
    tmc5160_write_reg(tmc, TMC_REG_IHOLD_IRUN,
                      IHOLD_IRUN(ihold, irun, iholddelay));
}

/* ──────────────────────────────────────────────
 * Ramp Configuration
 * ────────────────────────────────────────────── */

void tmc5160_set_ramp(tmc5160_t *tmc, uint32_t vmax, uint32_t amax,
                      uint32_t dmax)
{
    tmc5160_write_reg(tmc, TMC_REG_VMAX, vmax);
    tmc5160_write_reg(tmc, TMC_REG_AMAX, amax);
    tmc5160_write_reg(tmc, TMC_REG_DMAX, dmax);
}

/* ──────────────────────────────────────────────
 * Motion Commands
 * ────────────────────────────────────────────── */

void tmc5160_move_to(tmc5160_t *tmc, int32_t position)
{
    tmc5160_write_reg(tmc, TMC_REG_RAMPMODE, RAMPMODE_POSITION);
    tmc5160_write_reg(tmc, TMC_REG_XTARGET, (uint32_t)position);
}

void tmc5160_move_velocity(tmc5160_t *tmc, int32_t velocity)
{
    if (velocity >= 0) {
        tmc5160_write_reg(tmc, TMC_REG_RAMPMODE, RAMPMODE_VELOCITY_POS);
        tmc5160_write_reg(tmc, TMC_REG_VMAX, (uint32_t)velocity);
    } else {
        tmc5160_write_reg(tmc, TMC_REG_RAMPMODE, RAMPMODE_VELOCITY_NEG);
        tmc5160_write_reg(tmc, TMC_REG_VMAX, (uint32_t)(-velocity));
    }
}

void tmc5160_stop(tmc5160_t *tmc)
{
    /* Set velocity mode with VMAX=0 to decelerate */
    tmc5160_write_reg(tmc, TMC_REG_VMAX, 0);
    tmc5160_write_reg(tmc, TMC_REG_RAMPMODE, RAMPMODE_VELOCITY_POS);
}

/* ──────────────────────────────────────────────
 * Position
 * ────────────────────────────────────────────── */

bool tmc5160_position_reached(tmc5160_t *tmc)
{
    uint32_t rampstat = tmc5160_read_reg(tmc, TMC_REG_RAMPSTAT);
    return (rampstat & RAMPSTAT_POSITION_REACHED) != 0;
}

int32_t tmc5160_get_position(tmc5160_t *tmc)
{
    return (int32_t)tmc5160_read_reg(tmc, TMC_REG_XACTUAL);
}

void tmc5160_set_position(tmc5160_t *tmc, int32_t position)
{
    tmc5160_write_reg(tmc, TMC_REG_XACTUAL, (uint32_t)position);
    tmc5160_write_reg(tmc, TMC_REG_XTARGET, (uint32_t)position);
}

/* ──────────────────────────────────────────────
 * StallGuard2
 * ────────────────────────────────────────────── */

void tmc5160_set_stallguard(tmc5160_t *tmc, int8_t threshold)
{
    /* TCOOLTHRS must be set for StallGuard to work */
    tmc5160_write_reg(tmc, TMC_REG_TCOOLTHRS, 0x000FFFFF);

    /* COOLCONF: set SGT field */
    tmc5160_write_reg(tmc, TMC_REG_COOLCONF,
                      COOLCONF_SGT((uint8_t)threshold));
}

/* ──────────────────────────────────────────────
 * Status Polling
 * ────────────────────────────────────────────── */

uint32_t tmc5160_poll_status(tmc5160_t *tmc)
{
    tmc->drv_status = tmc5160_read_reg(tmc, TMC_REG_DRVSTATUS);
    tmc->sg_result = (uint16_t)(tmc->drv_status & DRVSTAT_SG_RESULT_MASK);
    tmc->cs_actual = (uint16_t)((tmc->drv_status & DRVSTAT_CS_ACTUAL_MASK)
                                >> DRVSTAT_CS_ACTUAL_SHIFT);
    tmc->xactual = tmc5160_get_position(tmc);

    return tmc->drv_status;
}

bool tmc5160_has_fault(const tmc5160_t *tmc)
{
    return (tmc->drv_status & DRVSTAT_FAULT_MASK) != 0;
}

/* ──────────────────────────────────────────────
 * Error Handling
 * ────────────────────────────────────────────── */

void tmc5160_clear_errors(tmc5160_t *tmc)
{
    tmc5160_write_reg(tmc, TMC_REG_GSTAT,
                      GSTAT_RESET | GSTAT_DRV_ERR | GSTAT_UV_CP);
}

/* ──────────────────────────────────────────────
 * Chopper Configuration
 * ────────────────────────────────────────────── */

void tmc5160_set_chopconf(tmc5160_t *tmc, uint32_t chopconf)
{
    tmc5160_write_reg(tmc, TMC_REG_CHOPCONF, chopconf);
}

/* ──────────────────────────────────────────────
 * Motor HAL Adapter
 * ────────────────────────────────────────────── */

#include "motor_hal.h"
#include "motor_config.h"

static motor_result_t tmc5160_hal_init(void *drv_ctx)
{
    tmc5160_t *tmc = (tmc5160_t *)drv_ctx;
    if (tmc == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    bool ok = tmc5160_init(tmc, tmc->axis, tmc->cs_index);
    return ok ? MOTOR_OK : MOTOR_ERR_DRIVER_FAULT;
}

static motor_result_t tmc5160_hal_move_abs(void *drv_ctx, int32_t target_steps,
                                           uint32_t vmax, uint32_t amax)
{
    tmc5160_t *tmc = (tmc5160_t *)drv_ctx;
    if (tmc == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    tmc5160_set_ramp(tmc, vmax, amax, amax);
    tmc5160_move_to(tmc, target_steps);
    return MOTOR_OK;
}

static bool tmc5160_hal_position_reached(void *drv_ctx)
{
    return tmc5160_position_reached((tmc5160_t *)drv_ctx);
}

static int32_t tmc5160_hal_get_position(void *drv_ctx)
{
    return tmc5160_get_position((tmc5160_t *)drv_ctx);
}

static void tmc5160_hal_emergency_stop(void *drv_ctx)
{
    tmc5160_t *tmc = (tmc5160_t *)drv_ctx;
    if (tmc != NULL) {
        tmc5160_stop(tmc);
        hal_gpio_write(HAL_GPIO_DRV_ENN, true);
    }
}

static motor_result_t tmc5160_hal_poll_status(void *drv_ctx,
                                              motor_status_t *out)
{
    tmc5160_t *tmc = (tmc5160_t *)drv_ctx;
    if ((tmc == NULL) || (out == NULL)) {
        return MOTOR_ERR_INVALID_PARAM;
    }

    uint32_t ds = tmc5160_poll_status(tmc);

    out->ot        = (uint8_t)((ds & DRVSTAT_OT) != 0U);
    out->otpw      = (uint8_t)((ds & DRVSTAT_OTPW) != 0U);
    out->s2ga      = (uint8_t)((ds & DRVSTAT_S2GA) != 0U);
    out->s2gb      = (uint8_t)((ds & DRVSTAT_S2GB) != 0U);
    out->ola       = (uint8_t)((ds & DRVSTAT_OLa) != 0U);
    out->olb       = (uint8_t)((ds & DRVSTAT_OLb) != 0U);
    out->stall     = 0U;
    out->sg_result = (int16_t)tmc->sg_result;

    /* Check RAMPSTAT for StallGuard event */
    uint32_t rs = tmc5160_read_reg(tmc, TMC_REG_RAMPSTAT);
    if ((rs & RAMPSTAT_STATUS_SG) != 0U) {
        out->stall = 1U;
    }

    if (tmc5160_has_fault(tmc)) {
        if ((ds & DRVSTAT_OT) != 0U) {
            return MOTOR_ERR_OVERTEMP;
        }
        return MOTOR_ERR_SHORT;
    }

    return MOTOR_OK;
}

static void tmc5160_hal_enable(void *drv_ctx)
{
    tmc5160_enable((tmc5160_t *)drv_ctx);
}

static void tmc5160_hal_disable(void *drv_ctx)
{
    tmc5160_disable((tmc5160_t *)drv_ctx);
}

static const motor_hal_ops_t s_tmc5160_ops = {
    .init             = tmc5160_hal_init,
    .move_abs         = tmc5160_hal_move_abs,
    .position_reached = tmc5160_hal_position_reached,
    .get_position     = tmc5160_hal_get_position,
    .emergency_stop   = tmc5160_hal_emergency_stop,
    .poll_status      = tmc5160_hal_poll_status,
    .enable           = tmc5160_hal_enable,
    .disable          = tmc5160_hal_disable,
};

const motor_hal_ops_t *tmc5160_get_motor_hal_ops(void)
{
    return &s_tmc5160_ops;
}
