/**
 * @file board.c
 * @brief Board-level HAL for ortho-bender i.MX8MP M7 core
 *
 * Real hardware register access for GPIO (i.MX8MP GPIO4/5), ECSPI2 (SPI),
 * GPT1..4 timers, and RPMsg (rpmsg_lite over MU).  Replaces the earlier stubs
 * with production-ready implementations.
 *
 * Memory usage: ~300 bytes .bss (GPIO map + callbacks + RPMsg handles)
 * No dynamic allocation after init (RPMsg uses heap_4 during init only).
 *
 * IEC 62304 SW Class: B
 */

#include "board.h"
#include "hal_gpio.h"
#include "hal_spi.h"
#include "hal_gpt.h"
#include "step_gen.h"
#include "error_codes.h"

#include <stddef.h>
#include <string.h>

/* MCUXpresso SDK device header -- provides GPT_Type, GPIO_Type, ECSPI_Type,
 * register masks, IRQ numbers, and peripheral base pointers (GPT1..GPT4,
 * GPIO3..GPIO5, ECSPI2, MUB).  Requires CPU_MIMX8ML8CVNKZ defined. */
#include "MIMX8ML8_cm7.h"

/* CMSIS core for NVIC, __DSB, etc. */
#include "core_cm7.h"

/* NXP MU (Messaging Unit) driver — needed by rpmsg_mu_init_early() */
#include "fsl_mu.h"

/* RPMsg-Lite headers */
#include "rpmsg_lite.h"
#include "rpmsg_queue.h"
#include "rpmsg_ns.h"

/* FreeRTOS */
#include "FreeRTOS.h"
#include "task.h"

/* Machine config for safety constants */
#include "estop.h"
#include "machine_config.h"

/* ======================================================================
 * GPIO Pin Mapping: hal_gpio_pin_t -> (GPIO bank, bit position)
 *
 * Pin assignments are for the ortho-bender carrier board Rev A.
 * GPIO4 is the primary bank for motor control signals (directly accessible
 * by M7 without RDC conflicts with A53 Linux).
 * ====================================================================== */

/** GPIO bank + pin for each HAL pin */
typedef struct {
    GPIO_Type   *port;      /**< GPIO peripheral base pointer */
    uint8_t      pin;       /**< Bit position within the bank (0..31) */
    IRQn_Type    irq_lo;    /**< Combined IRQ for pins 0..15 */
    IRQn_Type    irq_hi;    /**< Combined IRQ for pins 16..31 */
} gpio_pin_map_t;

/**
 * Pin map table.  Index = hal_gpio_pin_t enum value.
 *
 * GPIO4 pins chosen for motor signals (M7-owned via RDC).
 * GPIO5 used for safety signals to keep them on a separate IRQ path.
 */
static const gpio_pin_map_t s_gpio_map[HAL_GPIO_COUNT] = {
    /* STEP/DIR pins -- GPIO4 */
    [HAL_GPIO_STEP0]      = { GPIO4,  0, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_DIR0]       = { GPIO4,  1, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_STEP1]      = { GPIO4,  2, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_DIR1]       = { GPIO4,  3, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_STEP2]      = { GPIO4,  4, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_DIR2]       = { GPIO4,  5, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_STEP3]      = { GPIO4,  6, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_DIR3]       = { GPIO4,  7, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },

    /* TMC260C-PA SPI CS pins -- GPIO4 */
    [HAL_GPIO_TMC_SPI_CS0] = { GPIO4,  8, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_TMC_SPI_CS1] = { GPIO4,  9, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_TMC_SPI_CS2] = { GPIO4, 10, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_TMC_SPI_CS3] = { GPIO4, 11, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },

    /* TMC DIAG pins (input, active-low) -- GPIO4 */
    [HAL_GPIO_TMC_DIAG0]  = { GPIO4, 12, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_TMC_DIAG1]  = { GPIO4, 13, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_TMC_DIAG2]  = { GPIO4, 14, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },
    [HAL_GPIO_TMC_DIAG3]  = { GPIO4, 15, GPIO4_Combined_0_15_IRQn, GPIO4_Combined_16_31_IRQn },

    /* Safety -- GPIO5 (separate IRQ domain from motor signals) */
    [HAL_GPIO_DRV_ENN]    = { GPIO5,  0, GPIO5_Combined_0_15_IRQn, GPIO5_Combined_16_31_IRQn },
    [HAL_GPIO_ESTOP_IN]   = { GPIO5,  1, GPIO5_Combined_0_15_IRQn, GPIO5_Combined_16_31_IRQn },

    /* Homing -- GPIO5 */
    [HAL_GPIO_HOME_BEND]  = { GPIO5,  2, GPIO5_Combined_0_15_IRQn, GPIO5_Combined_16_31_IRQn },
};

/** Registered IRQ callbacks per pin */
static hal_gpio_callback_t s_gpio_callbacks[HAL_GPIO_COUNT];

/* ======================================================================
 * Board Init
 * ====================================================================== */

void board_init(void)
{
    board_clock_init();
    board_pin_mux_init();
}

void board_clock_init(void)
{
    /*
     * Clock tree configuration for M7-owned peripherals.
     *
     * On i.MX8MP, the A53 Linux kernel typically configures the main PLLs
     * and assigns clocks to peripherals.  The M7 can access CCM target root
     * registers to set its own peripheral clocks.  However, for peripherals
     * that Linux also uses (e.g., CCM), we rely on the initial configuration
     * from U-Boot / ATF.
     *
     * Assumed clock setup (from U-Boot/ATF):
     *   - M7 core: 800 MHz (SYSTEM_PLL2_CLK / 2)
     *   - ECSPI2:  20 MHz from SYSTEM_PLL1_CLK / 40 (we divide further in ECSPI)
     *   - GPT1..4: 24 MHz from OSC_24M (crystal)
     *   - GPIO:    no clock gating needed (always-on domain)
     *
     * TODO: Add explicit CCM target root configuration if U-Boot does not
     *       set up ECSPI2 and GPT clocks for M7 use.
     */
}

void board_pin_mux_init(void)
{
    /*
     * IOMUXC pin mux configuration.
     *
     * On i.MX8MP, pin muxing is typically done by A53 Linux or U-Boot via
     * device tree.  For M7-owned pins, we can configure IOMUXC directly.
     *
     * GPIO4[0..15]:  Must be muxed to GPIO (ALT5) mode.
     * GPIO5[0..2]:   Must be muxed to GPIO (ALT5) mode.
     * ECSPI2:        MOSI/MISO/SCLK on their native ECSPI2 pads.
     *
     * TODO: Write IOMUXC_SW_MUX_CTL_PAD registers for GPIO4/5 pins.
     *       The exact pad names depend on the carrier board schematic.
     *       For now, we assume U-Boot/device-tree has configured these.
     */
}

/* ======================================================================
 * GPIO HAL -- Real i.MX8MP register access
 * ====================================================================== */

bool hal_gpio_init(hal_gpio_pin_t pin, hal_gpio_dir_t dir, bool initial_value)
{
    if ((uint32_t)pin >= HAL_GPIO_COUNT) {
        return false;
    }

    const gpio_pin_map_t *map = &s_gpio_map[pin];
    GPIO_Type *gpio = map->port;
    uint32_t mask = 1U << map->pin;

    if (dir == HAL_GPIO_DIR_OUTPUT) {
        /* Set initial output value before enabling output driver */
        if (initial_value) {
            gpio->DR |= mask;
        } else {
            gpio->DR &= ~mask;
        }
        /* Set direction to output */
        gpio->GDIR |= mask;
    } else {
        /* Set direction to input */
        gpio->GDIR &= ~mask;
    }

    return true;
}

bool hal_gpio_read(hal_gpio_pin_t pin)
{
    if ((uint32_t)pin >= HAL_GPIO_COUNT) {
        return false;
    }

    const gpio_pin_map_t *map = &s_gpio_map[pin];
    GPIO_Type *gpio = map->port;
    uint32_t mask = 1U << map->pin;

    /* Read from PSR (pad status register) for inputs,
     * or DR (data register) for outputs */
    if ((gpio->GDIR & mask) != 0U) {
        return (gpio->DR & mask) != 0U;
    }
    return (gpio->PSR & mask) != 0U;
}

void hal_gpio_write(hal_gpio_pin_t pin, bool value)
{
    if ((uint32_t)pin >= HAL_GPIO_COUNT) {
        return;
    }

    const gpio_pin_map_t *map = &s_gpio_map[pin];
    GPIO_Type *gpio = map->port;
    uint32_t mask = 1U << map->pin;

    if (value) {
        gpio->DR |= mask;
    } else {
        gpio->DR &= ~mask;
    }
}

void hal_gpio_toggle(hal_gpio_pin_t pin)
{
    if ((uint32_t)pin >= HAL_GPIO_COUNT) {
        return;
    }

    const gpio_pin_map_t *map = &s_gpio_map[pin];
    GPIO_Type *gpio = map->port;
    uint32_t mask = 1U << map->pin;

    gpio->DR ^= mask;
}

bool hal_gpio_irq_attach(hal_gpio_pin_t pin, hal_gpio_edge_t edge,
                         hal_gpio_callback_t callback)
{
    if ((uint32_t)pin >= HAL_GPIO_COUNT) {
        return false;
    }

    const gpio_pin_map_t *map = &s_gpio_map[pin];
    GPIO_Type *gpio = map->port;
    uint8_t bit = map->pin;

    s_gpio_callbacks[pin] = callback;

    /* Configure interrupt edge in ICR1 (pins 0..15) or ICR2 (pins 16..31).
     * ICR field encoding: 00=low-level, 01=high-level, 10=rising, 11=falling.
     * For EDGE_BOTH, use EDGE_SEL register instead. */
    uint32_t icr_val = 0U;
    switch (edge) {
    case HAL_GPIO_EDGE_RISING:
        icr_val = 2U;
        gpio->EDGE_SEL &= ~(1U << bit);
        break;
    case HAL_GPIO_EDGE_FALLING:
        icr_val = 3U;
        gpio->EDGE_SEL &= ~(1U << bit);
        break;
    case HAL_GPIO_EDGE_BOTH:
        /* EDGE_SEL overrides ICR for this pin */
        gpio->EDGE_SEL |= (1U << bit);
        break;
    default:
        gpio->EDGE_SEL &= ~(1U << bit);
        break;
    }

    if (edge != HAL_GPIO_EDGE_BOTH) {
        if (bit < 16U) {
            uint32_t shift = (uint32_t)bit * 2U;
            gpio->ICR1 = (gpio->ICR1 & ~(3U << shift)) | (icr_val << shift);
        } else {
            uint32_t shift = (uint32_t)(bit - 16U) * 2U;
            gpio->ICR2 = (gpio->ICR2 & ~(3U << shift)) | (icr_val << shift);
        }
    }

    return true;
}

void hal_gpio_irq_enable(hal_gpio_pin_t pin)
{
    if ((uint32_t)pin >= HAL_GPIO_COUNT) {
        return;
    }

    const gpio_pin_map_t *map = &s_gpio_map[pin];
    GPIO_Type *gpio = map->port;
    uint32_t mask = 1U << map->pin;

    /* Clear any pending interrupt first */
    gpio->ISR = mask;

    /* Enable interrupt for this pin */
    gpio->IMR |= mask;

    /* Enable NVIC for the appropriate combined IRQ */
    IRQn_Type irq = (map->pin < 16U) ? map->irq_lo : map->irq_hi;
    NVIC_SetPriority(irq, 2U);  /* Priority 2: below GPT (1), above default */
    NVIC_EnableIRQ(irq);
}

void hal_gpio_irq_disable(hal_gpio_pin_t pin)
{
    if ((uint32_t)pin >= HAL_GPIO_COUNT) {
        return;
    }

    const gpio_pin_map_t *map = &s_gpio_map[pin];
    GPIO_Type *gpio = map->port;
    uint32_t mask = 1U << map->pin;

    gpio->IMR &= ~mask;
}

/* ── GPIO Combined IRQ Handlers ── */

/**
 * @brief Dispatch GPIO interrupts for a given bank
 *
 * Reads ISR, masks with IMR, iterates set bits, calls registered callbacks.
 */
static void gpio_bank_irq_handler(GPIO_Type *gpio,
                                  uint8_t pin_start, uint8_t pin_end)
{
    uint32_t flags = gpio->ISR & gpio->IMR;

    for (uint8_t bit = pin_start; bit <= pin_end; bit++) {
        uint32_t mask = 1U << bit;
        if ((flags & mask) != 0U) {
            /* Clear interrupt flag (write-1-to-clear) */
            gpio->ISR = mask;

            /* Find the HAL pin that maps to this bank+bit */
            for (uint32_t i = 0U; i < HAL_GPIO_COUNT; i++) {
                if (s_gpio_map[i].port == gpio && s_gpio_map[i].pin == bit) {
                    if (s_gpio_callbacks[i] != NULL) {
                        s_gpio_callbacks[i]((hal_gpio_pin_t)i);
                    }
                    break;
                }
            }
        }
    }
}

void GPIO4_Combined_0_15_IRQHandler(void)
{
    gpio_bank_irq_handler(GPIO4, 0U, 15U);
    __DSB();
}

void GPIO4_Combined_16_31_IRQHandler(void)
{
    gpio_bank_irq_handler(GPIO4, 16U, 31U);
    __DSB();
}

void GPIO5_Combined_0_15_IRQHandler(void)
{
    gpio_bank_irq_handler(GPIO5, 0U, 15U);
    __DSB();
}

void GPIO5_Combined_16_31_IRQHandler(void)
{
    gpio_bank_irq_handler(GPIO5, 16U, 31U);
    __DSB();
}

/* ======================================================================
 * SPI HAL -- ECSPI2 for TMC260C-PA
 *
 * i.MX8MP ECSPI2 at 0x30830000.
 * Mode 3 (CPOL=1, CPHA=1), 8-bit words, polled transfer.
 * CS is managed by GPIO (not ECSPI hardware CS) for flexibility with
 * multiple TMC260C-PA chips on the same bus.
 * ====================================================================== */

/** ECSPI reference clock assumed from CCM (Hz) */
#define ECSPI2_REF_CLK_HZ  20000000U

bool hal_spi_init(hal_spi_id_t id, const hal_spi_config_t *config)
{
    if (id != HAL_SPI_TMC || config == NULL) {
        return false;
    }

    ECSPI_Type *spi = ECSPI2;

    /* Disable ECSPI before configuration */
    spi->CONREG &= ~ECSPI_CONREG_EN_MASK;

    /* Software reset: disable and re-enable */
    spi->CONREG = 0U;

    /*
     * Clock divider calculation:
     *   ECSPI clock = ref_clk / ((PRE_DIVIDER + 1) * 2^POST_DIVIDER)
     *
     * For 2 MHz from 20 MHz reference:
     *   20 MHz / (10) = 2 MHz -> PRE=4, POST=1 -> (4+1)*2^1 = 10
     *   Or: PRE=9, POST=0 -> (9+1)*1 = 10
     */
    uint32_t target_hz = config->clock_hz;
    if (target_hz == 0U) {
        target_hz = 2000000U;  /* Default 2 MHz for TMC260C-PA */
    }

    uint32_t pre_div = 0U;
    uint32_t post_div = 0U;
    uint32_t best_div = ECSPI2_REF_CLK_HZ;

    /* Find best divider combination */
    for (uint32_t post = 0U; post < 16U; post++) {
        for (uint32_t pre = 0U; pre < 16U; pre++) {
            uint32_t div = (pre + 1U) * (1U << post);
            uint32_t freq = ECSPI2_REF_CLK_HZ / div;
            if (freq <= target_hz) {
                uint32_t err = target_hz - freq;
                uint32_t best_err = target_hz - (ECSPI2_REF_CLK_HZ / best_div);
                if (err < best_err) {
                    pre_div = pre;
                    post_div = post;
                    best_div = div;
                }
            }
        }
    }

    /* Burst length in bits minus 1.  For byte-by-byte: 7 (8-bit bursts) */
    uint32_t burst_bits = (uint32_t)config->bits;
    if (burst_bits == 0U) {
        burst_bits = 8U;
    }

    uint32_t conreg = 0U;
    conreg |= ECSPI_CONREG_EN(1U);             /* Enable */
    conreg |= ECSPI_CONREG_CHANNEL_MODE(0xFU); /* All channels master mode */
    conreg |= ECSPI_CONREG_PRE_DIVIDER(pre_div);
    conreg |= ECSPI_CONREG_POST_DIVIDER(post_div);
    conreg |= ECSPI_CONREG_BURST_LENGTH(burst_bits - 1U);
    conreg |= ECSPI_CONREG_SMC(1U);            /* Start transfer immediately on XCH */

    spi->CONREG = conreg;

    /*
     * CONFIGREG: clock phase and polarity per-channel.
     * Mode 3: CPOL=1, CPHA=1
     * Channel 0 is used (CHANNEL_SELECT = 0 in CONREG, default).
     * SCLK_PHA[0] = 1 (CPHA=1), SCLK_POL[0] = 1 (CPOL=1)
     * SCLK_CTL[0] = 1 (SCLK stays high when idle, matches CPOL=1)
     */
    uint32_t configreg = 0U;
    if (config->mode & 0x01U) {
        configreg |= ECSPI_CONFIGREG_SCLK_PHA(1U);   /* CPHA=1 for ch0 */
    }
    if (config->mode & 0x02U) {
        configreg |= ECSPI_CONFIGREG_SCLK_POL(1U);   /* CPOL=1 for ch0 */
        configreg |= ECSPI_CONFIGREG_SCLK_CTL(1U);   /* Idle high for ch0 */
    }
    spi->CONFIGREG = configreg;

    /* Sample period: use default (0) for fastest operation */
    spi->PERIODREG = 0U;

    /* Disable all interrupts -- we use polled mode */
    spi->INTREG = 0U;

    /* Clear any pending status flags */
    spi->STATREG = spi->STATREG;

    return true;
}

bool hal_spi_transfer(hal_spi_id_t id,
                      const uint8_t *tx_data, uint8_t *rx_data,
                      uint32_t len)
{
    if (id != HAL_SPI_TMC) {
        return false;
    }

    ECSPI_Type *spi = ECSPI2;

    for (uint32_t i = 0U; i < len; i++) {
        /* Wait for TX FIFO ready */
        uint32_t timeout = 10000U;
        while (((spi->STATREG & ECSPI_STATREG_TE_MASK) == 0U) && (timeout > 0U)) {
            timeout--;
        }
        if (timeout == 0U) {
            return false;
        }

        /* Write TX data */
        uint32_t tx_word = (tx_data != NULL) ? (uint32_t)tx_data[i] : 0U;
        spi->TXDATA = tx_word;

        /* Wait for transfer complete (RR = RX FIFO has data) */
        timeout = 10000U;
        while (((spi->STATREG & ECSPI_STATREG_RR_MASK) == 0U) && (timeout > 0U)) {
            timeout--;
        }
        if (timeout == 0U) {
            return false;
        }

        /* Read RX data */
        uint32_t rx_word = spi->RXDATA;
        if (rx_data != NULL) {
            rx_data[i] = (uint8_t)(rx_word & 0xFFU);
        }
    }

    /* Clear transfer complete flag */
    spi->STATREG = ECSPI_STATREG_TC_MASK;

    return true;
}

void hal_spi_cs_assert(hal_spi_id_t id, uint8_t cs_index)
{
    (void)id;
    if (cs_index >= 4U) {
        return;
    }
    /* CS pins are HAL_GPIO_TMC_SPI_CS0 + cs_index, active-low */
    hal_gpio_write((hal_gpio_pin_t)(HAL_GPIO_TMC_SPI_CS0 + cs_index), false);
}

void hal_spi_cs_deassert(hal_spi_id_t id, uint8_t cs_index)
{
    (void)id;
    if (cs_index >= 4U) {
        return;
    }
    hal_gpio_write((hal_gpio_pin_t)(HAL_GPIO_TMC_SPI_CS0 + cs_index), true);
}

/* ======================================================================
 * GPT Timer HAL -- i.MX8MP GPT1..GPT4
 *
 * GPT1 -> FEED axis (axis 0), IRQ 55
 * GPT2 -> BEND axis (axis 1), IRQ 54
 * GPT3 -> ROTATE axis (axis 2), IRQ 53
 * GPT4 -> LIFT axis (axis 3), IRQ 52
 *
 * Clock source: 24 MHz crystal oscillator (EN_24M mode).
 * Counter resets to 0 on compare match (restart mode, FRR=0).
 * Output compare channel 1 (OCR[0]) used for periodic interrupts.
 * ====================================================================== */

/** GPT peripheral base pointers indexed by channel */
static GPT_Type *const s_gpt_base[HAL_GPT_CH_COUNT] = {
    GPT1, GPT2, GPT3, GPT4
};

/** GPT IRQ numbers indexed by channel */
static const IRQn_Type s_gpt_irq[HAL_GPT_CH_COUNT] = {
    GPT1_IRQn, GPT2_IRQn, GPT3_IRQn, GPT4_IRQn
};

/** GPT clock source frequency (24 MHz crystal) */
#define GPT_CLK_SOURCE_HZ  24000000U

bool hal_gpt_init(hal_gpt_ch_t ch, uint32_t clock_hz)
{
    if ((uint32_t)ch >= HAL_GPT_CH_COUNT) {
        return false;
    }

    GPT_Type *gpt = s_gpt_base[ch];

    /* Software reset */
    gpt->CR = GPT_CR_SWR_MASK;
    while ((gpt->CR & GPT_CR_SWR_MASK) != 0U) {
        /* Wait for reset to complete */
    }

    /*
     * Prescaler to achieve target clock_hz from 24 MHz crystal.
     * GPT_PR = (source_clk / target_clk) - 1
     * Example: 24 MHz / 24 MHz = 1 -> PR = 0 (no prescaling)
     *          24 MHz / 1 MHz  = 24 -> PR = 23
     *
     * For step generation, we typically want the full 24 MHz for
     * maximum timing resolution.  If clock_hz == 0 or >= 24 MHz,
     * use no prescaler.
     */
    uint32_t prescaler = 0U;
    if (clock_hz > 0U && clock_hz < GPT_CLK_SOURCE_HZ) {
        prescaler = (GPT_CLK_SOURCE_HZ / clock_hz) - 1U;
        if (prescaler > 0xFFFU) {
            prescaler = 0xFFFU;  /* 12-bit prescaler max */
        }
    }
    gpt->PR = prescaler;

    /*
     * Control register:
     * - CLKSRC = 5 (crystal oscillator via EN_24M)
     * - EN_24M = 1 (enable 24 MHz crystal clock input)
     * - ENMOD  = 1 (counter resets to 0 when re-enabled)
     * - FRR    = 0 (restart mode: counter resets on compare match)
     * - EN     = 0 (leave disabled until hal_gpt_start)
     *
     * i.MX8MP GPT CLKSRC field: 5 = Crystal oscillator (24M)
     */
    gpt->CR = GPT_CR_CLKSRC(5U) |
              GPT_CR_EN_24M(1U) |
              GPT_CR_ENMOD(1U);
    /* FRR=0 is default (restart mode) -- counter resets on OCR match */

    /* Disable all interrupts initially */
    gpt->IR = 0U;

    /* Clear all status flags */
    gpt->SR = 0x3FU;  /* Write-1-to-clear all flags */

    /* Configure NVIC: high priority for step pulse timing */
    NVIC_SetPriority(s_gpt_irq[ch], 1U);  /* Priority 1: highest for motion */

    return true;
}

void hal_gpt_start(hal_gpt_ch_t ch, uint32_t period_ticks)
{
    if ((uint32_t)ch >= HAL_GPT_CH_COUNT) {
        return;
    }

    GPT_Type *gpt = s_gpt_base[ch];

    /* Disable timer before changing compare value */
    gpt->CR &= ~GPT_CR_EN_MASK;

    /* Set output compare register 1 */
    gpt->OCR[0] = period_ticks;

    /* Clear pending interrupt flags */
    gpt->SR = 0x3FU;

    /* Enable output compare 1 interrupt */
    gpt->IR = GPT_IR_OF1IE_MASK;

    /* Enable NVIC */
    NVIC_EnableIRQ(s_gpt_irq[ch]);

    /* Enable timer -- counter starts from 0 (ENMOD=1) */
    gpt->CR |= GPT_CR_EN_MASK;
}

void hal_gpt_stop(hal_gpt_ch_t ch)
{
    if ((uint32_t)ch >= HAL_GPT_CH_COUNT) {
        return;
    }

    GPT_Type *gpt = s_gpt_base[ch];

    /* Disable timer */
    gpt->CR &= ~GPT_CR_EN_MASK;

    /* Disable interrupt */
    gpt->IR = 0U;

    /* Disable NVIC for this GPT (prevents stale interrupts) */
    NVIC_DisableIRQ(s_gpt_irq[ch]);

    /* Clear pending flags */
    gpt->SR = 0x3FU;
}

void hal_gpt_set_period(hal_gpt_ch_t ch, uint32_t period_ticks)
{
    if ((uint32_t)ch >= HAL_GPT_CH_COUNT) {
        return;
    }

    GPT_Type *gpt = s_gpt_base[ch];

    /*
     * ISR-safe: writing OCR while timer is running.
     * In restart mode (FRR=0), the new compare value takes effect
     * immediately.  If the counter has already passed the new value,
     * it will wrap around and eventually match.
     */
    gpt->OCR[0] = period_ticks;
}

/* ======================================================================
 * GPT ISR Handlers
 *
 * Called from the vector table.  Each handler clears the GPT OF1 flag
 * and delegates to step_gen_isr() for the corresponding axis.
 * ====================================================================== */

void GPT1_IRQHandler(void)
{
    /* Clear output compare 1 flag (write-1-to-clear) */
    GPT1->SR = GPT_SR_OF1_MASK;
    step_gen_isr(0);
    __DSB();
}

void GPT2_IRQHandler(void)
{
    GPT2->SR = GPT_SR_OF1_MASK;
    step_gen_isr(1);
    __DSB();
}

void GPT3_IRQHandler(void)
{
    GPT3->SR = GPT_SR_OF1_MASK;
    step_gen_isr(2);
    __DSB();
}

void GPT4_IRQHandler(void)
{
    GPT4->SR = GPT_SR_OF1_MASK;
    step_gen_isr(3);
    __DSB();
}

/* ======================================================================
 * RPMsg HAL -- rpmsg_lite on i.MX8MP MU (Messaging Unit)
 *
 * Uses the NXP rpmsg_lite library with the imx8mp_m7 platform port.
 * The M7 acts as the "remote" side (A53 Linux is the "master").
 *
 * Shared memory at 0x55000000 (must match Linux DTS + rsc_table.c).
 * MU (Messaging Unit) B side at 0x30AB0000 for doorbell interrupts.
 *
 * Flow:
 *   1. rpmsg_lite_remote_init() -- sets up virtqueues in shared memory
 *   2. rpmsg_lite_wait_for_link_up() -- waits for Linux to start
 *   3. Create endpoint + queue for blocking receive
 *   4. rpmsg_ns_announce() -- announces "ortho-bender-ipc" to Linux
 *      Linux side creates /dev/rpmsg0 in response
 * ====================================================================== */

#include "rpmsg_config.h"

/** RPMsg instance and endpoint (module-static, no dynamic allocation) */
static struct rpmsg_lite_instance *s_rpmsg_instance = NULL;
static struct rpmsg_lite_endpoint *s_rpmsg_ept = NULL;
static rpmsg_queue_handle s_rpmsg_queue = NULL;

/** Tracks full RPMsg initialization (instance + queue + endpoint + NS) */
static bool s_rpmsg_initialized = false;

/** Remote (A53) endpoint address, learned from first received message */
static volatile uint32_t s_remote_addr = RL_ADDR_ANY;

/** Local endpoint address */
#define LOCAL_EPT_ADDR  (30U)

void rpmsg_mu_init_early(void)
{
    /*
     * Enable the MU (Messaging Unit) IRQ BEFORE the FreeRTOS scheduler starts.
     *
     * The Linux remoteproc driver sends a MU kick immediately after loading
     * the M7 firmware to signal virtio DRIVER_OK.  If MU1_M7_IRQn is not
     * enabled at that point, the kick times out (imx_rproc_kick err:-62)
     * and the virtio link never comes up.
     *
     * This function ONLY enables the MU interrupt — it does NOT create any
     * rpmsg_lite structures.  Full RPMsg initialization (with vTaskDelay-
     * based link-up wait) happens later in rpmsg_hal_init() from ipc_task,
     * after the FreeRTOS scheduler is running.
     *
     * MUB is the B-side (M7-side) of the Messaging Unit peripheral.
     */
    MU_Init(MUB);
    NVIC_SetPriority(MU1_M7_IRQn, 3U);
    NVIC_EnableIRQ(MU1_M7_IRQn);
}

bool rpmsg_hal_init(void)
{
    /* Guard: if fully initialized (instance + queue + endpoint), nothing to do */
    if (s_rpmsg_initialized) {
        return true;
    }

    /* If a partial instance exists from a prior failed attempt, tear it down
     * so we start fresh.  This handles the case where rpmsg_lite_remote_init
     * succeeded but link-up or endpoint creation failed. */
    if (s_rpmsg_instance != RL_NULL) {
        rpmsg_lite_deinit(s_rpmsg_instance);
        s_rpmsg_instance = RL_NULL;
    }

    /*
     * Initialize rpmsg_lite as remote.
     * rpmsg_platform.c handles MU_Init(MUB) and NVIC_EnableIRQ(MU1_M7_IRQn)
     * internally, but MU IRQ was already enabled by rpmsg_mu_init_early()
     * during hw_init() — the platform layer handles the double-init safely.
     */
    s_rpmsg_instance = rpmsg_lite_remote_init(
        (void *)RPMSG_LITE_SHMEM_BASE,
        RPMSG_LITE_LINK_ID,
        RL_NO_FLAGS
    );

    if (s_rpmsg_instance == RL_NULL) {
        return false;
    }

    /*
     * Wait for Linux virtio link up using the RTOS-aware blocking API.
     * This function calls vTaskDelay internally, so the scheduler MUST be
     * running.  rpmsg_mu_init_early() in hw_init() ensures the MU IRQ is
     * armed in time for the Linux DRIVER_OK kick; the actual link
     * negotiation completes here.
     *
     * Timeout: 30 seconds — generous to cover slow Linux boot.
     */
    int32_t link_rc = rpmsg_lite_wait_for_link_up(s_rpmsg_instance, 30000U);
    if (link_rc != RL_TRUE) {
        rpmsg_lite_deinit(s_rpmsg_instance);
        s_rpmsg_instance = RL_NULL;
        return false;
    }

    /* Create a receive queue (backed by FreeRTOS queue internally) */
    s_rpmsg_queue = rpmsg_queue_create(s_rpmsg_instance);
    if (s_rpmsg_queue == RL_NULL) {
        rpmsg_lite_deinit(s_rpmsg_instance);
        s_rpmsg_instance = RL_NULL;
        return false;
    }

    /* Create endpoint with the queue as the RX callback */
    s_rpmsg_ept = rpmsg_lite_create_ept(
        s_rpmsg_instance,
        LOCAL_EPT_ADDR,
        rpmsg_queue_rx_cb,
        s_rpmsg_queue
    );

    if (s_rpmsg_ept == RL_NULL) {
        rpmsg_queue_destroy(s_rpmsg_instance, s_rpmsg_queue);
        s_rpmsg_queue = RL_NULL;
        rpmsg_lite_deinit(s_rpmsg_instance);
        s_rpmsg_instance = RL_NULL;
        return false;
    }

    /* Announce endpoint name to Linux.  The Linux rpmsg_char/rpmsg_ctrl
     * driver will create /dev/rpmsg0 in response. */
    int32_t ns_rc = rpmsg_ns_announce(
        s_rpmsg_instance,
        s_rpmsg_ept,
        RPMSG_LITE_NS_ANNOUNCE_STRING,
        (uint32_t)RL_NS_CREATE
    );

    if (ns_rc != RL_SUCCESS) {
        /* NS announce failed — non-fatal, we can still receive.  Log only. */
    }

    s_rpmsg_initialized = true;
    return true;
}

bool rpmsg_hal_receive(uint8_t *buf, uint32_t buf_size,
                       uint32_t *received_len, uint32_t timeout_ms)
{
    if (s_rpmsg_instance == NULL || s_rpmsg_ept == NULL || s_rpmsg_queue == NULL) {
        return false;
    }

    if (received_len != NULL) {
        *received_len = 0U;
    }

    uint32_t src = 0U;
    uint32_t len = 0U;

    /* Convert timeout: 0 = infinite (RL_BLOCK), nonzero = ms */
    uintptr_t rl_timeout = (timeout_ms == 0U) ? RL_BLOCK : (uintptr_t)timeout_ms;

    int32_t rc = rpmsg_queue_recv(
        s_rpmsg_instance,
        s_rpmsg_queue,
        &src,
        (char *)buf,
        buf_size,
        &len,
        rl_timeout
    );

    if (rc != RL_SUCCESS) {
        return false;
    }

    /* Learn remote address from first message (for send path) */
    if (s_remote_addr == RL_ADDR_ANY) {
        s_remote_addr = src;
    }

    if (received_len != NULL) {
        *received_len = len;
    }

    return true;
}

bool rpmsg_hal_send(const uint8_t *buf, uint32_t len)
{
    if (s_rpmsg_instance == NULL || s_rpmsg_ept == NULL) {
        return false;
    }

    /* Use the learned remote address, or fall back to RL_ADDR_ANY */
    uint32_t dst = s_remote_addr;

    int32_t rc = rpmsg_lite_send(
        s_rpmsg_instance,
        s_rpmsg_ept,
        dst,
        (char *)buf,
        len,
        (uintptr_t)1000  /* 1 second timeout */
    );

    return (rc == RL_SUCCESS);
}

/* ======================================================================
 * Task Stubs (safety_task, status_task)
 *
 * These are referenced by main.c but not yet fully implemented.
 * Minimal loops to prevent linker errors and allow firmware boot.
 * ====================================================================== */

void safety_task(void *params)
{
    (void)params;

    /* STUB: 1 kHz safety check loop
     * Real implementation will:
     * - Check E-STOP GPIO state
     * - Pet hardware watchdog
     * - Monitor motor driver fault flags
     * - Check position soft limits
     */
    const TickType_t period = pdMS_TO_TICKS(SAFETY_CHECK_PERIOD_US / 1000U);
    if (period == 0) {
        /* SAFETY_CHECK_PERIOD_US is 100 us = 0.1 ms, rounds to 0 ticks.
         * Use 1 tick minimum to prevent busy-loop. */
    }

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1));  /* 1 ms minimum tick */

        /* Check E-STOP hardware state */
        /* estop_is_active() is safe to call from task context */
    }
}

void status_task(void *params)
{
    (void)params;

    /* STUB: 10 Hz status reporting loop
     * Real implementation will:
     * - Collect position/velocity from motion_task
     * - Collect TMC diagnostic data from tmc_poll_task
     * - Send MSG_STATUS_HEARTBEAT via ipc_send_to_a53()
     */
    const TickType_t period = pdMS_TO_TICKS(STATUS_REPORT_PERIOD_MS);

    for (;;) {
        vTaskDelay(period);
        /* TODO: Send periodic heartbeat/status to A53 */
    }
}

/* ======================================================================
 * FreeRTOS Static Allocation Callbacks
 *
 * Required when configSUPPORT_STATIC_ALLOCATION == 1.
 * Provides memory for the idle task and timer task.
 * ====================================================================== */

static StaticTask_t s_idle_task_tcb;
static StackType_t  s_idle_task_stack[configMINIMAL_STACK_SIZE];

void vApplicationGetIdleTaskMemory(StaticTask_t **ppxIdleTaskTCBBuffer,
                                   StackType_t **ppxIdleTaskStackBuffer,
                                   uint32_t *pulIdleTaskStackSize)
{
    *ppxIdleTaskTCBBuffer   = &s_idle_task_tcb;
    *ppxIdleTaskStackBuffer = s_idle_task_stack;
    *pulIdleTaskStackSize   = configMINIMAL_STACK_SIZE;
}

static StaticTask_t s_timer_task_tcb;
static StackType_t  s_timer_task_stack[configTIMER_TASK_STACK_DEPTH];

void vApplicationGetTimerTaskMemory(StaticTask_t **ppxTimerTaskTCBBuffer,
                                    StackType_t **ppxTimerTaskStackBuffer,
                                    uint32_t *pulTimerTaskStackSize)
{
    *ppxTimerTaskTCBBuffer   = &s_timer_task_tcb;
    *ppxTimerTaskStackBuffer = s_timer_task_stack;
    *pulTimerTaskStackSize   = configTIMER_TASK_STACK_DEPTH;
}

/* ======================================================================
 * Error Code String (used by error_codes.h declaration)
 * ====================================================================== */

const char *error_code_to_string(error_code_t code)
{
    switch (code) {
    case ERR_NONE:                  return "OK";
    case ERR_UNKNOWN:               return "Unknown error";
    case ERR_TIMEOUT:               return "Timeout";
    case ERR_INVALID_PARAM:         return "Invalid parameter";
    case ERR_BUSY:                  return "Busy";
    case ERR_NOT_INITIALIZED:       return "Not initialized";
    case ERR_MOTION_ESTOP_ACTIVE:   return "E-STOP active";
    case ERR_TMC_DRIVER_ERROR:      return "TMC driver error";
    default:                        return "Error";
    }
}
