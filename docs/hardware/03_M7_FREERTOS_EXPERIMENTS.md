# M7 FreeRTOS Experiment Code

Source: EVK bring-up workspace (quarkers/workspace/m7_pwm_gpio_count_uart/)

---

## Overview

Proof-of-concept M7 FreeRTOS firmware tested on i.MX8MP EVK:
- **PWM generation**: GPT1 ISR toggles GPIO at 1200Hz (600Hz square wave, 50% duty)
- **Input capture**: GPIO rising-edge IRQ counter
- **Reporting**: FreeRTOS task prints edge count every 1s via UART

## Key Peripherals Used

| Peripheral | Usage | Pin |
|-----------|-------|-----|
| GPIO1_IO00 | PWM output | `IOMUXC_GPIO1_IO00_GPIO1_IO00` |
| GPIO1_IO01 | Edge capture input | `IOMUXC_GPIO1_IO01_GPIO1_IO01` |
| GPT1 | Timer for PWM toggle ISR | — |
| LPUART2 | Debug output (115200 baud) | — |

## Architecture

```
GPT1 ISR (1200Hz)
  └── Toggle GPIO1_IO00 → 600Hz PWM output
                              │ (jumper wire)
                              ▼
GPIO1 IRQ (rising edge)
  └── Increment g_edgeCount

FreeRTOS ReporterTask (1s interval)
  └── Print delta count via LPUART2 (expect ~600/s)
```

## Relevance to Ortho-Bender

This experiment validates:
1. **GPT timer + ISR** — basis for stepper motor pulse generation
2. **GPIO IRQ counting** — basis for encoder feedback
3. **FreeRTOS task scheduling** — basis for motion control task architecture
4. **LPUART debug output** — M7 debug channel selection (avoid UART2 conflict with A53)

## Source Reference

Original file: `workspace/m7_pwm_gpio_count_uart/main_freertos.c` (161 lines)

The code uses NXP MCUXpresso SDK APIs:
- `fsl_gpio.h`, `fsl_gpt.h`, `fsl_lpuart.h`, `fsl_iomuxc.h`
- FreeRTOS `task.h` for thread management
