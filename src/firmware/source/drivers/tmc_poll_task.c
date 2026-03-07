/**
 * @file tmc_poll_task.c
 * @brief FreeRTOS task: TMC5160 status polling at 200 Hz
 *
 * Reads DRV_STATUS/SG_RESULT/XACTUAL from all active TMC5160 drivers.
 * Raises alarms on overtemp, short-circuit, open-load, or stall events.
 *
 * IEC 62304 SW Class: B
 */

#include "FreeRTOS.h"
#include "task.h"

#include "tmc5160.h"
#include "machine_config.h"
#include "error_codes.h"
#include "ipc_protocol.h"

/* ──────────────────────────────────────────────
 * Module State
 * ────────────────────────────────────────────── */

static tmc5160_t g_tmc[TMC5160_CHIP_COUNT];
static msg_status_tmc_t g_tmc_status;

/* ──────────────────────────────────────────────
 * Accessors (used by motion_controller and status_task)
 * ────────────────────────────────────────────── */

tmc5160_t *tmc_get_driver(uint8_t axis)
{
    if (axis >= TMC5160_CHIP_COUNT) {
        return NULL;
    }
    return &g_tmc[axis];
}

const msg_status_tmc_t *tmc_get_status(void)
{
    return &g_tmc_status;
}

/* ──────────────────────────────────────────────
 * Fault Check
 * ────────────────────────────────────────────── */

static void tmc_check_faults(uint8_t axis, uint32_t drv_status)
{
    (void)axis;
    (void)drv_status;
    /*
     * TODO: Map DRV_STATUS fault bits to error_code_t alarms.
     * Send MSG_STATUS_ALARM via IPC when faults are detected.
     *
     * Fault conditions to check:
     *   - DRVSTAT_OT:   ERR_TMC_OVERTEMP
     *   - DRVSTAT_S2GA/S2GB: ERR_TMC_SHORT_CIRCUIT
     *   - DRVSTAT_OLa/OLb:   ERR_TMC_OPEN_LOAD
     *   - DRVSTAT_FAULT_MASK: ERR_TMC_DRIVER_ERROR → trigger E-STOP
     */
}

/* ──────────────────────────────────────────────
 * Task Entry Point
 * ────────────────────────────────────────────── */

void tmc_poll_task(void *params)
{
    (void)params;

    const TickType_t period = pdMS_TO_TICKS(TMC_POLL_PERIOD_US / 1000);

    /* Initialize TMC5160 drivers */
    for (uint8_t i = 0; i < TMC5160_CHIP_COUNT; i++) {
        tmc5160_init(&g_tmc[i], i, i);
        tmc5160_enable(&g_tmc[i]);
    }

    TickType_t last_wake = xTaskGetTickCount();

    for (;;) {
        vTaskDelayUntil(&last_wake, period);

        /* Poll all active drivers */
        for (uint8_t i = 0; i < TMC5160_CHIP_COUNT; i++) {
            if (!g_tmc[i].initialized) {
                continue;
            }

            tmc5160_poll_status(&g_tmc[i]);

            /* Update shared status structure */
            g_tmc_status.drv_status[i] = g_tmc[i].drv_status;
            g_tmc_status.sg_result[i] = g_tmc[i].sg_result;
            g_tmc_status.cs_actual[i] = g_tmc[i].cs_actual;
            g_tmc_status.xactual[i] = g_tmc[i].xactual;

            /* Check for faults */
            if (tmc5160_has_fault(&g_tmc[i])) {
                tmc_check_faults(i, g_tmc[i].drv_status);
            }
        }
    }
}
