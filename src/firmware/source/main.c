/**
 * @file main.c
 * @brief Ortho-Bender M7 firmware entry point
 * @note Initializes hardware, creates FreeRTOS tasks, starts scheduler
 *
 * IEC 62304 SW Class: B
 *
 * Task Architecture (priority descending):
 *   safety_task     (6) -  1 kHz: E-STOP (SW + HW DRV_ENN), watchdog
 *   motion_task     (5) - 100 Hz: trajectory sequence manager (TMC5160 ramp)
 *   tmc_poll_task   (4) - 200 Hz: TMC5160 DRV_STATUS/SG_RESULT via SPI
 *   ipc_task        (3) - Event:  RPMsg command processing
 *   status_task     (2) -  10 Hz: periodic status reporting to A53
 *   idle_task        (0) - Idle:   WDT pet, power management
 */

#include <stdint.h>
#include <stdbool.h>
#include "FreeRTOS.h"
#include "task.h"

#include "board.h"
#include "ipc_protocol.h"
#include "machine_config.h"
#include "error_codes.h"

/* ──────────────────────────────────────────────
 * Task Handles
 * ────────────────────────────────────────────── */

static TaskHandle_t h_safety_task    = NULL;
static TaskHandle_t h_motion_task    = NULL;
static TaskHandle_t h_tmc_poll_task  = NULL;
static TaskHandle_t h_ipc_task       = NULL;
static TaskHandle_t h_status_task    = NULL;

/* ──────────────────────────────────────────────
 * Task Priorities
 * ────────────────────────────────────────────── */

#define PRIORITY_SAFETY     (configMAX_PRIORITIES - 1)  /* Highest */
#define PRIORITY_MOTION     (configMAX_PRIORITIES - 2)
#define PRIORITY_TMC_POLL   (configMAX_PRIORITIES - 3)
#define PRIORITY_IPC        (configMAX_PRIORITIES - 4)
#define PRIORITY_STATUS     (configMAX_PRIORITIES - 5)

/* ──────────────────────────────────────────────
 * Task Stack Sizes (words)
 * ────────────────────────────────────────────── */

#define STACK_SAFETY        512U
#define STACK_MOTION        1024U
#define STACK_TMC_POLL      512U
#define STACK_IPC           1024U
#define STACK_STATUS        512U

/* ──────────────────────────────────────────────
 * Task Functions (defined in respective modules)
 * ────────────────────────────────────────────── */

extern void safety_task(void *params);
extern void motion_task(void *params);
extern void tmc_poll_task(void *params);
extern void ipc_task(void *params);
extern void status_task(void *params);

/* ──────────────────────────────────────────────
 * Hardware Initialization
 * ────────────────────────────────────────────── */

/* rpmsg_mu_init_early declared in board.c — enables MU IRQ only */
extern void rpmsg_mu_init_early(void);

static void hw_init(void)
{
    /* Board-level initialization (clocks, pin-mux) */
    board_init();

    /*
     * Enable the MU (Messaging Unit) IRQ BEFORE the FreeRTOS scheduler starts.
     *
     * The Linux remoteproc driver sends a MU kick immediately after loading
     * the firmware to signal virtio DRIVER_OK.  If MU1_M7_IRQn is not
     * enabled at that point, the kick times out (err:-62) and the virtio
     * link never comes up.
     *
     * rpmsg_mu_init_early() ONLY enables the MU interrupt hardware.  It does
     * NOT create rpmsg_lite structures or wait for link-up.
     *
     * Full RPMsg initialization (with scheduler-safe vTaskDelay-based link-up
     * wait, endpoint creation, and NS announce) happens in ipc_task() via
     * rpmsg_hal_init() after the scheduler is running.
     */
    rpmsg_mu_init_early();
}

/* ──────────────────────────────────────────────
 * Main
 * ────────────────────────────────────────────── */

int main(void)
{
    /* Phase 1: Hardware init (before scheduler) */
    hw_init();

    /* Phase 2: Create tasks */
    xTaskCreate(safety_task,   "safety",   STACK_SAFETY,    NULL, PRIORITY_SAFETY,   &h_safety_task);
    xTaskCreate(motion_task,   "motion",   STACK_MOTION,    NULL, PRIORITY_MOTION,   &h_motion_task);
    xTaskCreate(tmc_poll_task, "tmc_poll", STACK_TMC_POLL,  NULL, PRIORITY_TMC_POLL, &h_tmc_poll_task);
    xTaskCreate(ipc_task,      "ipc",      STACK_IPC,       NULL, PRIORITY_IPC,      &h_ipc_task);
    xTaskCreate(status_task,   "status",   STACK_STATUS,    NULL, PRIORITY_STATUS,   &h_status_task);

    /* Phase 3: Start scheduler (never returns) */
    vTaskStartScheduler();

    /* Should never reach here */
    for (;;) {}
}

/* ──────────────────────────────────────────────
 * FreeRTOS Hooks
 * ────────────────────────────────────────────── */

void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName)
{
    (void)xTask;
    (void)pcTaskName;
    /* TODO: Log fault, trigger E-STOP */
    for (;;) {}
}

void vApplicationMallocFailedHook(void)
{
    /* Dynamic allocation after init is forbidden */
    /* TODO: Log fault, trigger E-STOP */
    for (;;) {}
}
