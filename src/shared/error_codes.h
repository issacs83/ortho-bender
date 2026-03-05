/**
 * @file error_codes.h
 * @brief System-wide error codes for ortho-bender
 *
 * IEC 62304 SW Class: B
 */

#ifndef ORTHO_BENDER_ERROR_CODES_H
#define ORTHO_BENDER_ERROR_CODES_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    /* General (0x0000 - 0x00FF) */
    ERR_NONE                    = 0x0000,
    ERR_UNKNOWN                 = 0x0001,
    ERR_TIMEOUT                 = 0x0002,
    ERR_INVALID_PARAM           = 0x0003,
    ERR_BUSY                    = 0x0004,
    ERR_NOT_INITIALIZED         = 0x0005,

    /* IPC (0x0100 - 0x01FF) */
    ERR_IPC_INVALID_MAGIC       = 0x0100,
    ERR_IPC_INVALID_MSG_TYPE    = 0x0101,
    ERR_IPC_PAYLOAD_TOO_LARGE   = 0x0102,
    ERR_IPC_SEND_FAILED         = 0x0103,
    ERR_IPC_RECV_TIMEOUT        = 0x0104,

    /* Motion (0x0200 - 0x02FF) */
    ERR_MOTION_NOT_HOMED        = 0x0200,
    ERR_MOTION_LIMIT_HIT        = 0x0201,
    ERR_MOTION_FOLLOWING_ERROR  = 0x0202,
    ERR_MOTION_OVERCURRENT      = 0x0203,
    ERR_MOTION_STALL_DETECTED   = 0x0204,
    ERR_MOTION_ESTOP_ACTIVE     = 0x0205,
    ERR_MOTION_INVALID_BCODE    = 0x0206,

    /* Sensor (0x0300 - 0x03FF) */
    ERR_SENSOR_FORCE_OVERLOAD   = 0x0300,
    ERR_SENSOR_TEMP_OVERTEMP    = 0x0301,
    ERR_SENSOR_ENCODER_FAULT    = 0x0302,
    ERR_SENSOR_ADC_FAULT        = 0x0303,
    ERR_SENSOR_NOT_CALIBRATED   = 0x0304,

    /* Safety (0x0400 - 0x04FF) */
    ERR_SAFETY_ESTOP_HW         = 0x0400,   /* Hardware E-STOP pressed */
    ERR_SAFETY_ESTOP_SW         = 0x0401,   /* Software E-STOP triggered */
    ERR_SAFETY_WATCHDOG         = 0x0402,   /* Watchdog timeout */
    ERR_SAFETY_FORCE_LIMIT      = 0x0403,   /* Bending force exceeded limit */
    ERR_SAFETY_TEMP_LIMIT       = 0x0404,   /* Temperature exceeded limit */
    ERR_SAFETY_POS_LIMIT        = 0x0405,   /* Position exceeded soft limit */

    /* Wire/Material (0x0500 - 0x05FF) */
    ERR_WIRE_BREAKAGE           = 0x0500,
    ERR_WIRE_SLIP               = 0x0501,
    ERR_WIRE_MATERIAL_UNKNOWN   = 0x0502,

    /* NPU / Vision (0x0600 - 0x06FF) */
    ERR_NPU_LOAD_FAILED         = 0x0600,
    ERR_NPU_INFERENCE_FAILED    = 0x0601,
    ERR_VISION_CAMERA_FAULT     = 0x0602,
    ERR_VISION_CALIBRATION      = 0x0603,

} error_code_t;

/**
 * @brief Get human-readable error string
 */
const char* error_code_to_string(error_code_t code);

#ifdef __cplusplus
}
#endif

#endif /* ORTHO_BENDER_ERROR_CODES_H */
