/**
 * @file main.c
 * @brief Ortho-Bender M7 firmware entry point
 * @note Initializes hardware, creates FreeRTOS tasks, starts scheduler
 *
 * IEC 62304 SW Class: B
 *
 * Task Architecture (priority descending):
 *   safety_task  (6) - 10 kHz: E-STOP, limits, watchdog
 *   motion_task  (5) -  1 kHz: PID loops, trajectory execution
 *   sensor_task  (4) -  1 kHz: ADC, encoder, force, temperature
 *   ipc_task     (3) - Event:  RPMsg command processing
 *   status_task  (2) - 100 Hz: Periodic status reporting to A53
 *   idle_task    (0) - Idle:   WDT pet, power management
 */

#include <stdint.h>
#include "FreeRTOS.h"
#include "task.h"

#include "board.h"
#include "ipc_protocol.h"
#include "machine_config.h"
#include "error_codes.h"

/* ──────────────────────────────────────────────
 * Task Handles
 * ────────────────────────────────────────────── */

static TaskHandle_t h_safety_task   = NULL;
static TaskHandle_t h_motion_task   = NULL;
static TaskHandle_t h_sensor_task   = NULL;
static TaskHandle_t h_ipc_task      = NULL;
static TaskHandle_t h_status_task   = NULL;

/* ──────────────────────────────────────────────
 * Task Priorities
 * ────────────────────────────────────────────── */

#define PRIORITY_SAFETY     (configMAX_PRIORITIES - 1)  /* Highest */
#define PRIORITY_MOTION     (configMAX_PRIORITIES - 2)
#define PRIORITY_SENSOR     (configMAX_PRIORITIES - 3)
#define PRIORITY_IPC        (configMAX_PRIORITIES - 4)
#define PRIORITY_STATUS     (configMAX_PRIORITIES - 5)

/* ──────────────────────────────────────────────
 * Task Stack Sizes (words)
 * ────────────────────────────────────────────── */

#define STACK_SAFETY        512U
#define STACK_MOTION        1024U
#define STACK_SENSOR        512U
#define STACK_IPC           1024U
#define STACK_STATUS        512U

/* ──────────────────────────────────────────────
 * Task Functions (defined in respective modules)
 * ────────────────────────────────────────────── */

extern void safety_task(void *params);
extern void motion_task(void *params);
extern void sensor_task(void *params);
extern void ipc_task(void *params);
extern void status_task(void *params);

/* ──────────────────────────────────────────────
 * Hardware Initialization
 * ────────────────────────────────────────────── */

static void hw_init(void)
{
    /* Board-level initialization */
    board_init();

    /* TODO: Initialize HAL peripherals */
    /* hal_gpio_init(); */
    /* hal_spi_init(); */
    /* hal_i2c_init(); */
    /* hal_pwm_init(); */
    /* hal_adc_init(); */
    /* hal_timer_init(); */
    /* hal_uart_init(); */
}

/* ──────────────────────────────────────────────
 * Main
 * ────────────────────────────────────────────── */

int main(void)
{
    /* Phase 1: Hardware init (before scheduler) */
    hw_init();

    /* Phase 2: Create tasks */
    xTaskCreate(safety_task, "safety", STACK_SAFETY, NULL, PRIORITY_SAFETY, &h_safety_task);
    xTaskCreate(motion_task, "motion", STACK_MOTION, NULL, PRIORITY_MOTION, &h_motion_task);
    xTaskCreate(sensor_task, "sensor", STACK_SENSOR, NULL, PRIORITY_SENSOR, &h_sensor_task);
    xTaskCreate(ipc_task,    "ipc",    STACK_IPC,    NULL, PRIORITY_IPC,    &h_ipc_task);
    xTaskCreate(status_task, "status", STACK_STATUS, NULL, PRIORITY_STATUS, &h_status_task);

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
