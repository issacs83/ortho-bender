/**
 * @file tmc_poll_task.c
 * @brief FreeRTOS task: TMC260C-PA status polling at 200 Hz
 *
 * Reads status/SG_RESULT from all active TMC260C-PA drivers via SPI.
 * Raises alarms on overtemp, short-circuit, open-load, or stall events.
 *
 * IEC 62304 SW Class: B
 */

#include "FreeRTOS.h"
#include "task.h"

#include "tmc260c.h"
#include "machine_config.h"
#include "error_codes.h"
#include "ipc_protocol.h"

/* ──────────────────────────────────────────────
 * Module State
 * ────────────────────────────────────────────── */

static tmc260c_t g_tmc[AXIS_MAX];
static msg_status_tmc_t g_tmc_status;

/* ──────────────────────────────────────────────
 * Accessors (used by motion_controller and status_task)
 * ────────────────────────────────────────────── */

tmc260c_t *tmc_get_driver(uint8_t axis)
{
    if (axis >= AXIS_MAX) {
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

    /* Initialize TMC260C-PA drivers.
     * cs_index == axis index (each axis has dedicated CS GPIO).
     * DRV_ENN is controlled by the safety_task via GPIO, not here. */
    for (uint8_t i = 0; i < AXIS_MAX; i++) {
        tmc260c_init(&g_tmc[i], i, i);
    }

    TickType_t last_wake = xTaskGetTickCount();

    for (;;) {
        vTaskDelayUntil(&last_wake, period);

        /* Poll all active drivers */
        for (uint8_t i = 0; i < AXIS_MAX; i++) {
            if (!g_tmc[i].initialized) {
                continue;
            }

            tmc260c_read_status(&g_tmc[i]);

            /* Update shared status structure.
             * TMC260C-PA has no internal position register (STEP/DIR mode);
             * xactual is tracked in software by step_gen.c. */
            g_tmc_status.drv_status[i] = (uint32_t)g_tmc[i].status_flags;
            g_tmc_status.sg_result[i]  = g_tmc[i].sg_result;
            g_tmc_status.cs_actual[i]  = (uint16_t)g_tmc[i].current_scale;
            g_tmc_status.xactual[i]    = 0;    /* provided by step_gen.c */

            /* Check for faults */
            if (tmc260c_has_fault(&g_tmc[i])) {
                tmc_check_faults(i, (uint32_t)g_tmc[i].status_flags);
            }
        }
    }
}
