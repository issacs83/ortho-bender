/**
 * @file tmc5072.c
 * @brief TMC5072 dual-axis stepper motor driver -- SPI communication and control
 * @author ortho-bender firmware team
 *
 * SPI Protocol (TMC5072 Datasheet 4.1):
 *   Write: [0x80 | reg_addr] [data_31:24] [data_23:16] [data_15:8] [data_7:0]
 *   Read:  [reg_addr]        [0x00]       [0x00]       [0x00]      [0x00]
 *          (response arrives on the NEXT transfer)
 *
 * The TMC5072 contains two independent motor controllers.  Each motor has its
 * own register bank: motor 0 uses base addresses, motor 1 uses base + 0x20
 * for ramp registers.  Per-motor chopper/driver registers are at fixed offsets:
 *   Motor 0: CHOPCONF=0x6C, DRV_STATUS=0x6F
 *   Motor 1: CHOPCONF=0x7C, DRV_STATUS=0x7F
 *
 * Memory: ~52 bytes per tmc5072_t instance (static allocation).
 * No dynamic memory allocation.
 *
 * IEC 62304 SW Class: B
 */

#include "tmc5072.h"
#include "motor_hal.h"
#include "motor_config.h"
#include "hal_spi.h"
#include "hal_gpio.h"
#include "machine_config.h"

#include <stddef.h>
#include <string.h>

/* ======================================================================
 * SPI Helpers
 * ====================================================================== */

#define TMC5072_SPI_WRITE_BIT   0x80U
#define TMC5072_SPI_FRAME_LEN   5U

static void tmc5072_spi_transfer(uint8_t cs_index,
                                 const uint8_t tx[TMC5072_SPI_FRAME_LEN],
                                 uint8_t rx[TMC5072_SPI_FRAME_LEN])
{
    hal_spi_cs_assert(HAL_SPI_TMC, cs_index);
    (void)hal_spi_transfer(HAL_SPI_TMC, tx, rx, TMC5072_SPI_FRAME_LEN);
    hal_spi_cs_deassert(HAL_SPI_TMC, cs_index);
}

/* ======================================================================
 * Internal: per-motor register address helpers
 * ====================================================================== */

/**
 * @brief Get the RAMPMODE register address for the given motor index
 */
static uint8_t tmc5072_rampmode_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_RAMPMODE_0
                            : (uint8_t)TMC5072_REG_RAMPMODE_1;
}

static uint8_t tmc5072_xactual_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_XACTUAL_0
                            : (uint8_t)TMC5072_REG_XACTUAL_1;
}

static uint8_t tmc5072_xtarget_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_XTARGET_0
                            : (uint8_t)TMC5072_REG_XTARGET_1;
}

static uint8_t tmc5072_vmax_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_VMAX_0
                            : (uint8_t)TMC5072_REG_VMAX_1;
}

static uint8_t tmc5072_amax_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_AMAX_0
                            : (uint8_t)TMC5072_REG_AMAX_1;
}

static uint8_t tmc5072_dmax_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_DMAX_0
                            : (uint8_t)TMC5072_REG_DMAX_1;
}

static uint8_t tmc5072_rampstat_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_RAMPSTAT_0
                            : (uint8_t)TMC5072_REG_RAMPSTAT_1;
}

static uint8_t tmc5072_drvstatus_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_DRVSTATUS_0
                            : (uint8_t)TMC5072_REG_DRVSTATUS_1;
}

static uint8_t tmc5072_chopconf_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_CHOPCONF_0
                            : (uint8_t)TMC5072_REG_CHOPCONF_1;
}

static uint8_t tmc5072_coolconf_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_COOLCONF_0
                            : (uint8_t)TMC5072_REG_COOLCONF_1;
}

static uint8_t tmc5072_ihold_irun_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_IHOLD_IRUN_0
                            : (uint8_t)TMC5072_REG_IHOLD_IRUN_1_REAL;
}

static uint8_t tmc5072_vstart_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_VSTART_0
                            : (uint8_t)TMC5072_REG_VSTART_1;
}

static uint8_t tmc5072_vstop_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_VSTOP_0
                            : (uint8_t)TMC5072_REG_VSTOP_1;
}

static uint8_t tmc5072_a1_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_A1_0
                            : (uint8_t)TMC5072_REG_A1_1;
}

static uint8_t tmc5072_v1_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_V1_0
                            : (uint8_t)TMC5072_REG_V1_1;
}

static uint8_t tmc5072_d1_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_D1_0
                            : (uint8_t)TMC5072_REG_D1_1;
}

static uint8_t tmc5072_tzerowait_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_TZEROWAIT_0
                            : (uint8_t)TMC5072_REG_TZEROWAIT_1;
}

static uint8_t tmc5072_tcoolthrs_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_TCOOLTHRS_0
                            : (uint8_t)TMC5072_REG_TCOOLTHRS_1;
}

static uint8_t tmc5072_tpowerdown_reg(uint8_t axis_idx)
{
    return (axis_idx == 0U) ? (uint8_t)TMC5072_REG_TPOWERDOWN_0
                            : (uint8_t)TMC5072_REG_TPOWERDOWN_1;
}

/* ======================================================================
 * Register Access
 * ====================================================================== */

void tmc5072_write_reg(tmc5072_t *tmc, uint8_t reg, uint32_t value)
{
    uint8_t tx[TMC5072_SPI_FRAME_LEN] = {0U};
    uint8_t rx[TMC5072_SPI_FRAME_LEN] = {0U};

    tx[0] = TMC5072_SPI_WRITE_BIT | (reg & 0x7FU);
    tx[1] = (uint8_t)((value >> 24) & 0xFFU);
    tx[2] = (uint8_t)((value >> 16) & 0xFFU);
    tx[3] = (uint8_t)((value >> 8) & 0xFFU);
    tx[4] = (uint8_t)(value & 0xFFU);

    tmc5072_spi_transfer(tmc->cs_index, tx, rx);
}

uint32_t tmc5072_read_reg(tmc5072_t *tmc, uint8_t reg)
{
    uint8_t tx[TMC5072_SPI_FRAME_LEN] = {0U};
    uint8_t rx[TMC5072_SPI_FRAME_LEN] = {0U};

    /* First transfer: send address (response is stale) */
    tx[0] = reg & 0x7FU;
    tmc5072_spi_transfer(tmc->cs_index, tx, rx);

    /* Second transfer: read actual data */
    tx[0] = reg & 0x7FU;
    tmc5072_spi_transfer(tmc->cs_index, tx, rx);

    return ((uint32_t)rx[1] << 24) |
           ((uint32_t)rx[2] << 16) |
           ((uint32_t)rx[3] << 8) |
           (uint32_t)rx[4];
}

/* ======================================================================
 * Initialization
 * ====================================================================== */

bool tmc5072_init(tmc5072_t *tmc, uint8_t axis, uint8_t cs_index,
                  uint8_t axis_idx)
{
    if (tmc == NULL) {
        return false;
    }
    if (axis_idx > 1U) {
        return false;
    }

    tmc->axis        = axis;
    tmc->cs_index    = cs_index;
    tmc->axis_idx    = axis_idx;
    tmc->initialized = false;
    tmc->enabled     = false;
    tmc->drv_status  = 0U;
    tmc->sg_result   = 0U;
    tmc->xactual     = 0;

    /* Clear GSTAT (shared between both motors) */
    tmc5072_write_reg(tmc, TMC5072_REG_GSTAT,
                      TMC5072_GSTAT_RESET | TMC5072_GSTAT_DRV_ERR1 |
                      TMC5072_GSTAT_DRV_ERR2 | TMC5072_GSTAT_UV_CP);

    /* Verify SPI communication */
    uint32_t gstat = tmc5072_read_reg(tmc, TMC5072_REG_GSTAT);
    if (gstat == 0xFFFFFFFFU) {
        return false;
    }

    /* CHOPCONF: SpreadCycle, 16 microsteps */
    tmc5072_write_reg(tmc, tmc5072_chopconf_reg(axis_idx),
                      TMC5072_CHOPCONF_DEFAULT);

    /* Set default current */
    tmc5072_set_current(tmc, TMC5160_IHOLD_DEFAULT,
                        TMC5160_IRUN_DEFAULT,
                        TMC5160_IHOLDDELAY_DEFAULT);

    /* Default ramp parameters */
    tmc5072_write_reg(tmc, tmc5072_vstart_reg(axis_idx), 1U);
    tmc5072_write_reg(tmc, tmc5072_vstop_reg(axis_idx), 10U);
    tmc5072_write_reg(tmc, tmc5072_a1_reg(axis_idx), 1000U);
    tmc5072_write_reg(tmc, tmc5072_v1_reg(axis_idx), 50000U);
    tmc5072_write_reg(tmc, tmc5072_d1_reg(axis_idx), 1400U);
    tmc5072_write_reg(tmc, tmc5072_tzerowait_reg(axis_idx), 0U);

    /* Position mode */
    tmc5072_write_reg(tmc, tmc5072_rampmode_reg(axis_idx),
                      TMC5072_RAMPMODE_POSITION);

    /* Set position to 0 */
    tmc5072_write_reg(tmc, tmc5072_xactual_reg(axis_idx), 0U);
    tmc5072_write_reg(tmc, tmc5072_xtarget_reg(axis_idx), 0U);

    /* TPOWERDOWN: power down after 2 seconds standstill */
    tmc5072_write_reg(tmc, tmc5072_tpowerdown_reg(axis_idx), 200U);

    tmc->initialized = true;
    return true;
}

/* ======================================================================
 * Enable / Disable
 * ====================================================================== */

void tmc5072_enable(tmc5072_t *tmc)
{
    if (tmc == NULL) {
        return;
    }
    hal_gpio_write(HAL_GPIO_DRV_ENN, false);
    tmc->enabled = true;
}

void tmc5072_disable(tmc5072_t *tmc)
{
    if (tmc == NULL) {
        return;
    }
    hal_gpio_write(HAL_GPIO_DRV_ENN, true);
    tmc->enabled = false;
}

/* ======================================================================
 * Current Control
 * ====================================================================== */

void tmc5072_set_current(tmc5072_t *tmc, uint8_t ihold, uint8_t irun,
                         uint8_t iholddelay)
{
    if (tmc == NULL) {
        return;
    }
    tmc5072_write_reg(tmc, tmc5072_ihold_irun_reg(tmc->axis_idx),
                      TMC5072_IHOLD_IRUN(ihold, irun, iholddelay));
}

/* ======================================================================
 * Ramp Configuration
 * ====================================================================== */

void tmc5072_set_ramp(tmc5072_t *tmc, uint32_t vmax, uint32_t amax,
                      uint32_t dmax)
{
    if (tmc == NULL) {
        return;
    }
    tmc5072_write_reg(tmc, tmc5072_vmax_reg(tmc->axis_idx), vmax);
    tmc5072_write_reg(tmc, tmc5072_amax_reg(tmc->axis_idx), amax);
    tmc5072_write_reg(tmc, tmc5072_dmax_reg(tmc->axis_idx), dmax);
}

/* ======================================================================
 * Motion Commands
 * ====================================================================== */

void tmc5072_move_to(tmc5072_t *tmc, int32_t position)
{
    if (tmc == NULL) {
        return;
    }
    tmc5072_write_reg(tmc, tmc5072_rampmode_reg(tmc->axis_idx),
                      TMC5072_RAMPMODE_POSITION);
    tmc5072_write_reg(tmc, tmc5072_xtarget_reg(tmc->axis_idx),
                      (uint32_t)position);
}

void tmc5072_stop(tmc5072_t *tmc)
{
    if (tmc == NULL) {
        return;
    }
    tmc5072_write_reg(tmc, tmc5072_vmax_reg(tmc->axis_idx), 0U);
    tmc5072_write_reg(tmc, tmc5072_rampmode_reg(tmc->axis_idx),
                      TMC5072_RAMPMODE_VEL_POS);
}

/* ======================================================================
 * Position
 * ====================================================================== */

bool tmc5072_position_reached(tmc5072_t *tmc)
{
    if (tmc == NULL) {
        return true;
    }
    uint32_t rampstat = tmc5072_read_reg(tmc,
                                          tmc5072_rampstat_reg(tmc->axis_idx));
    return (rampstat & TMC5072_RAMPSTAT_POS_REACHED) != 0U;
}

int32_t tmc5072_get_position(tmc5072_t *tmc)
{
    if (tmc == NULL) {
        return 0;
    }
    return (int32_t)tmc5072_read_reg(tmc,
                                      tmc5072_xactual_reg(tmc->axis_idx));
}

void tmc5072_set_position(tmc5072_t *tmc, int32_t position)
{
    if (tmc == NULL) {
        return;
    }
    tmc5072_write_reg(tmc, tmc5072_xactual_reg(tmc->axis_idx),
                      (uint32_t)position);
    tmc5072_write_reg(tmc, tmc5072_xtarget_reg(tmc->axis_idx),
                      (uint32_t)position);
}

/* ======================================================================
 * StallGuard2
 * ====================================================================== */

void tmc5072_set_stallguard(tmc5072_t *tmc, int8_t threshold)
{
    if (tmc == NULL) {
        return;
    }
    tmc5072_write_reg(tmc, tmc5072_tcoolthrs_reg(tmc->axis_idx), 0x000FFFFFU);
    tmc5072_write_reg(tmc, tmc5072_coolconf_reg(tmc->axis_idx),
                      TMC5072_COOLCONF_SGT((uint8_t)threshold));
}

/* ======================================================================
 * Status Polling
 * ====================================================================== */

uint32_t tmc5072_poll_status(tmc5072_t *tmc)
{
    if (tmc == NULL) {
        return 0U;
    }
    tmc->drv_status = tmc5072_read_reg(tmc,
                                        tmc5072_drvstatus_reg(tmc->axis_idx));
    tmc->sg_result = (uint16_t)(tmc->drv_status & TMC5072_DRVSTAT_SG_MASK);
    tmc->xactual = tmc5072_get_position(tmc);
    return tmc->drv_status;
}

bool tmc5072_has_fault(const tmc5072_t *tmc)
{
    if (tmc == NULL) {
        return true;
    }
    return (tmc->drv_status & TMC5072_DRVSTAT_FAULT_MASK) != 0U;
}

void tmc5072_clear_errors(tmc5072_t *tmc)
{
    if (tmc == NULL) {
        return;
    }
    tmc5072_write_reg(tmc, TMC5072_REG_GSTAT,
                      TMC5072_GSTAT_RESET | TMC5072_GSTAT_DRV_ERR1 |
                      TMC5072_GSTAT_DRV_ERR2 | TMC5072_GSTAT_UV_CP);
}

/* ======================================================================
 * Motor HAL Adapter
 * ====================================================================== */

static motor_result_t tmc5072_hal_init(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    if (tmc == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    /* Re-init with stored params (axis, cs_index, axis_idx already set) */
    bool ok = tmc5072_init(tmc, tmc->axis, tmc->cs_index, tmc->axis_idx);
    return ok ? MOTOR_OK : MOTOR_ERR_DRIVER_FAULT;
}

static motor_result_t tmc5072_hal_move_abs(void *drv_ctx, int32_t target_steps,
                                           uint32_t vmax, uint32_t amax)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    if (tmc == NULL) {
        return MOTOR_ERR_INVALID_PARAM;
    }
    tmc5072_set_ramp(tmc, vmax, amax, amax);
    tmc5072_move_to(tmc, target_steps);
    return MOTOR_OK;
}

static bool tmc5072_hal_position_reached(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    return tmc5072_position_reached(tmc);
}

static int32_t tmc5072_hal_get_position(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    return tmc5072_get_position(tmc);
}

static void tmc5072_hal_emergency_stop(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    if (tmc != NULL) {
        tmc5072_stop(tmc);
        hal_gpio_write(HAL_GPIO_DRV_ENN, true);
    }
}

static motor_result_t tmc5072_hal_poll_status(void *drv_ctx,
                                              motor_status_t *out)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    if ((tmc == NULL) || (out == NULL)) {
        return MOTOR_ERR_INVALID_PARAM;
    }

    uint32_t ds = tmc5072_poll_status(tmc);

    out->ot        = (uint8_t)((ds & TMC5072_DRVSTAT_OT) != 0U);
    out->otpw      = (uint8_t)((ds & TMC5072_DRVSTAT_OTPW) != 0U);
    out->s2ga      = (uint8_t)((ds & TMC5072_DRVSTAT_S2GA) != 0U);
    out->s2gb      = (uint8_t)((ds & TMC5072_DRVSTAT_S2GB) != 0U);
    out->ola       = (uint8_t)((ds & TMC5072_DRVSTAT_OLA) != 0U);
    out->olb       = (uint8_t)((ds & TMC5072_DRVSTAT_OLB) != 0U);
    out->stall     = 0U;  /* Read from RAMPSTAT */
    out->sg_result = (int16_t)tmc->sg_result;

    /* Check RAMPSTAT for StallGuard event */
    uint32_t rs = tmc5072_read_reg(tmc,
                                    tmc5072_rampstat_reg(tmc->axis_idx));
    if ((rs & TMC5072_RAMPSTAT_SG) != 0U) {
        out->stall = 1U;
    }

    if (tmc5072_has_fault(tmc)) {
        if ((ds & TMC5072_DRVSTAT_OT) != 0U) {
            return MOTOR_ERR_OVERTEMP;
        }
        return MOTOR_ERR_SHORT;
    }

    return MOTOR_OK;
}

static void tmc5072_hal_enable(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    tmc5072_enable(tmc);
}

static void tmc5072_hal_disable(void *drv_ctx)
{
    tmc5072_t *tmc = (tmc5072_t *)drv_ctx;
    tmc5072_disable(tmc);
}

static const motor_hal_ops_t s_tmc5072_ops = {
    .init             = tmc5072_hal_init,
    .move_abs         = tmc5072_hal_move_abs,
    .position_reached = tmc5072_hal_position_reached,
    .get_position     = tmc5072_hal_get_position,
    .emergency_stop   = tmc5072_hal_emergency_stop,
    .poll_status      = tmc5072_hal_poll_status,
    .enable           = tmc5072_hal_enable,
    .disable          = tmc5072_hal_disable,
};

const motor_hal_ops_t *tmc5072_get_motor_hal_ops(void)
{
    return &s_tmc5072_ops;
}
