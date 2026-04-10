/**
 * @file FreeRTOSConfig.h
 * @brief FreeRTOS kernel configuration for i.MX8MP Cortex-M7
 *
 * IEC 62304 SW Class: B
 */

#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

/* ──────────────────────────────────────────────
 * Hardware / Clock
 * ────────────────────────────────────────────── */

#define configCPU_CLOCK_HZ                      400000000U  /* 400 MHz M7 core clock */
#define configTICK_RATE_HZ                      ((TickType_t)1000)

/* ──────────────────────────────────────────────
 * Scheduler
 * ────────────────────────────────────────────── */

#define configUSE_PREEMPTION                    1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION  1
#define configUSE_TICKLESS_IDLE                  0
#define configMAX_PRIORITIES                     8
#define configIDLE_SHOULD_YIELD                  1
#define configUSE_TIME_SLICING                   0  /* No time-slicing; strict priority */

/* ──────────────────────────────────────────────
 * Memory
 * ────────────────────────────────────────────── */

#define configMINIMAL_STACK_SIZE                ((uint16_t)128)
#define configTOTAL_HEAP_SIZE                   ((size_t)(50 * 1024))
#define configSUPPORT_STATIC_ALLOCATION          1
#define configSUPPORT_DYNAMIC_ALLOCATION         1
#define configAPPLICATION_ALLOCATED_HEAP          0

/* ──────────────────────────────────────────────
 * Task features
 * ────────────────────────────────────────────── */

#define configMAX_TASK_NAME_LEN                 16
#define configUSE_16_BIT_TICKS                  0
#define configUSE_MUTEXES                       1
#define configUSE_RECURSIVE_MUTEXES             1
#define configUSE_COUNTING_SEMAPHORES           1
#define configUSE_TASK_NOTIFICATIONS             1
#define configTASK_NOTIFICATION_ARRAY_ENTRIES    1
#define configQUEUE_REGISTRY_SIZE               8

/* ──────────────────────────────────────────────
 * Hook functions
 * ────────────────────────────────────────────── */

#define configUSE_IDLE_HOOK                     0
#define configUSE_TICK_HOOK                     0
#define configCHECK_FOR_STACK_OVERFLOW          2  /* Method 2: pattern check */
#define configUSE_MALLOC_FAILED_HOOK            1

/* ──────────────────────────────────────────────
 * Software timer
 * ────────────────────────────────────────────── */

#define configUSE_TIMERS                        1
#define configTIMER_TASK_PRIORITY               (configMAX_PRIORITIES - 1)
#define configTIMER_QUEUE_LENGTH                10
#define configTIMER_TASK_STACK_DEPTH            (configMINIMAL_STACK_SIZE * 2)

/* ──────────────────────────────────────────────
 * Cortex-M7 interrupt priority (i.MX8MP: 4 priority bits)
 * ────────────────────────────────────────────── */

#ifdef __NVIC_PRIO_BITS
#define configPRIO_BITS                         __NVIC_PRIO_BITS
#else
#define configPRIO_BITS                         4
#endif

/* Lowest interrupt priority usable by FreeRTOS kernel-aware ISRs */
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY          15
/* Highest interrupt priority that can call FreeRTOS API (FromISR).
 * Must be <= APP_MU_IRQ_PRIORITY (3) in rpmsg_platform.c so the MU ISR
 * can safely call xQueueSendFromISR / portYIELD_FROM_ISR. */
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY     3

#define configKERNEL_INTERRUPT_PRIORITY          (configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8 - configPRIO_BITS))
#define configMAX_SYSCALL_INTERRUPT_PRIORITY     (configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8 - configPRIO_BITS))

/* ──────────────────────────────────────────────
 * API includes
 * ────────────────────────────────────────────── */

#define INCLUDE_vTaskPrioritySet                1
#define INCLUDE_uxTaskPriorityGet               1
#define INCLUDE_vTaskDelete                     1
#define INCLUDE_vTaskSuspend                    1
#define INCLUDE_vTaskDelayUntil                 1
#define INCLUDE_vTaskDelay                      1
#define INCLUDE_xTaskGetSchedulerState          1
#define INCLUDE_xTaskGetCurrentTaskHandle       1
#define INCLUDE_eTaskGetState                   1
#define INCLUDE_xTimerPendFunctionCall          1

/* ──────────────────────────────────────────────
 * Assert
 * ────────────────────────────────────────────── */

#define configASSERT(x) if ((x) == 0) { taskDISABLE_INTERRUPTS(); for (;;); }

#endif /* FREERTOS_CONFIG_H */
