/**
 * @file hal_spi.h
 * @brief SPI hardware abstraction layer
 * @note Platform-specific implementation provided per board.
 *       M7 firmware accesses SPI only through this interface.
 *
 * IEC 62304 SW Class: B
 */

#ifndef HAL_SPI_H
#define HAL_SPI_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** SPI instance identifier */
typedef enum {
    HAL_SPI_TMC = 0,    /* SPI bus for TMC260C-PA motor drivers */
    HAL_SPI_COUNT
} hal_spi_id_t;

/** SPI configuration */
typedef struct {
    uint32_t    clock_hz;       /* SCK frequency */
    uint8_t     mode;           /* SPI mode (0-3) */
    uint8_t     bits;           /* Bits per word (8, 16, 32) */
    uint16_t    cs_setup_ns;    /* CS assert to first SCK edge */
} hal_spi_config_t;

/**
 * @brief Initialize SPI peripheral
 * @param id SPI bus identifier
 * @param config Configuration parameters
 * @return true on success
 */
bool hal_spi_init(hal_spi_id_t id, const hal_spi_config_t *config);

/**
 * @brief Full-duplex SPI transfer
 * @param id SPI bus identifier
 * @param tx_data Data to transmit (NULL for read-only)
 * @param rx_data Buffer for received data (NULL for write-only)
 * @param len Number of bytes to transfer
 * @return true on success
 */
bool hal_spi_transfer(hal_spi_id_t id,
                      const uint8_t *tx_data, uint8_t *rx_data,
                      uint32_t len);

/**
 * @brief Assert chip-select for a specific device on the SPI bus
 * @param id SPI bus identifier
 * @param cs_index Chip-select index (0 = first TMC260C-PA, etc.)
 */
void hal_spi_cs_assert(hal_spi_id_t id, uint8_t cs_index);

/**
 * @brief De-assert chip-select
 * @param id SPI bus identifier
 * @param cs_index Chip-select index
 */
void hal_spi_cs_deassert(hal_spi_id_t id, uint8_t cs_index);

#ifdef __cplusplus
}
#endif

#endif /* HAL_SPI_H */
