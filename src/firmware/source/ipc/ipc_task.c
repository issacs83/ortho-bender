/**
 * @file ipc_task.c
 * @brief FreeRTOS task: RPMsg IPC message handler (A53 <-> M7)
 * @author ortho-bender firmware team
 *
 * Processes incoming RPMsg messages from A53 Linux host.
 * Dispatches motion commands to motion_task via FreeRTOS queue.
 * Sends status responses and alarms back to A53.
 *
 * Protocol: ipc_protocol.h (header + payload, CRC-32 verified)
 * Transport: RPMsg over shared memory (mailbox interrupt driven)
 *
 * Memory: ~3.4 KB static (.bss: rx/tx buffers + queue), 0 bytes dynamic
 * Stack:  1024 words (from main.c STACK_IPC)
 *
 * IEC 62304 SW Class: B
 */

#include <string.h>

#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"

#include "ipc_protocol.h"
#include "machine_config.h"
#include "error_codes.h"
#include "estop.h"
#include "tmc260c.h"

/* ──────────────────────────────────────────────
 * Forward Declarations (from motion_task.c)
 * ────────────────────────────────────────────── */

/* Motion command envelope — must match motion_task.c definition */
typedef enum {
    MCMD_EXECUTE_BCODE  = 0,
    MCMD_JOG            = 1,
    MCMD_HOME           = 2,
    MCMD_STOP           = 3,
    MCMD_ESTOP          = 4,
    MCMD_RESET          = 5,
    MCMD_SET_PARAM      = 6,
    MCMD_WIRE_DETECT    = 7,
} motion_cmd_id_t;

typedef struct {
    motion_cmd_id_t cmd;
    union {
        msg_motion_bcode_t  bcode;
        msg_motion_jog_t    jog;
        msg_motion_home_t   home;
        msg_motion_param_t  param;
    } data;
} motion_cmd_t;

extern QueueHandle_t motion_get_cmd_queue(void);

/* From tmc_poll_task.c */
extern const msg_status_tmc_t *tmc_get_status(void);

/* From motion_controller.h */
extern motion_state_t motion_get_state(void);
extern void motion_get_positions(float positions[AXIS_MAX]);
extern void motion_estop(void);

/* ──────────────────────────────────────────────
 * Constants
 * ────────────────────────────────────────────── */

/** Maximum time to wait for motion queue space (ms) */
#define IPC_MOTION_QUEUE_TIMEOUT_MS     100U

/** Sequence number for outgoing messages */
static uint32_t s_tx_sequence = 0;

/* ──────────────────────────────────────────────
 * RPMsg HAL Stubs
 *
 * These functions must be implemented by the platform RPMsg driver.
 * On i.MX8MP M7, this wraps the MCUXpresso rpmsg_lite API.
 * ────────────────────────────────────────────── */

/**
 * @brief Initialize RPMsg transport
 * @return true on success
 */
extern bool rpmsg_hal_init(void);

/**
 * @brief Receive an RPMsg packet (blocking with timeout)
 * @param buf Buffer to receive into
 * @param buf_size Maximum buffer size
 * @param received_len Actual bytes received
 * @param timeout_ms Timeout in milliseconds (0 = forever)
 * @return true if a message was received
 */
extern bool rpmsg_hal_receive(uint8_t *buf, uint32_t buf_size,
                              uint32_t *received_len, uint32_t timeout_ms);

/**
 * @brief Send an RPMsg packet to A53
 * @param buf Data to send
 * @param len Length in bytes
 * @return true on success
 */
extern bool rpmsg_hal_send(const uint8_t *buf, uint32_t len);

/* ──────────────────────────────────────────────
 * TX Buffer (static — no dynamic allocation)
 * ────────────────────────────────────────────── */

static ipc_message_t s_tx_msg;

/* ──────────────────────────────────────────────
 * Public: Send IPC Message to A53
 * Called by motion_task for status/alarm reports.
 * ────────────────────────────────────────────── */

void ipc_send_to_a53(const ipc_message_t *msg)
{
    if (msg == NULL) {
        return;
    }

    uint32_t total_len = (uint32_t)sizeof(ipc_msg_header_t) + msg->header.payload_len;
    if (total_len > sizeof(ipc_message_t)) {
        total_len = sizeof(ipc_message_t);
    }

    (void)rpmsg_hal_send((const uint8_t *)msg, total_len);
}

/* ──────────────────────────────────────────────
 * Response Helpers
 * ────────────────────────────────────────────── */

/**
 * @brief Prepare tx message header with common fields
 */
static void ipc_prepare_header(uint16_t msg_type, uint16_t payload_len)
{
    (void)memset(&s_tx_msg, 0, sizeof(ipc_msg_header_t));
    s_tx_msg.header.magic = IPC_MAGIC;
    s_tx_msg.header.msg_type = msg_type;
    s_tx_msg.header.payload_len = payload_len;
    s_tx_msg.header.sequence = s_tx_sequence++;
    /* timestamp_us: filled by platform layer or set to tick count */
    s_tx_msg.header.timestamp_us = (uint64_t)xTaskGetTickCount() * 1000ULL;
}

/**
 * @brief Finalize and send tx message (compute CRC, send)
 */
static void ipc_finalize_and_send(void)
{
    s_tx_msg.header.crc32 = ipc_compute_crc32(&s_tx_msg);
    ipc_send_to_a53(&s_tx_msg);
}

/**
 * @brief Send NACK alarm response for protocol errors
 */
static void ipc_send_nack(error_code_t err_code)
{
    ipc_prepare_header(MSG_STATUS_ALARM, (uint16_t)sizeof(msg_status_alarm_t));

    msg_status_alarm_t *alarm = (msg_status_alarm_t *)s_tx_msg.payload;
    alarm->alarm_code = (uint32_t)err_code;
    alarm->severity = 0U;  /* warning level */
    alarm->axis = 0xFFU;   /* system-level */

    ipc_finalize_and_send();
}

/**
 * @brief Send MSG_STATUS_MOTION response
 */
static void ipc_send_status_motion(void)
{
    ipc_prepare_header(MSG_STATUS_MOTION, (uint16_t)sizeof(msg_status_motion_t));

    msg_status_motion_t *status = (msg_status_motion_t *)s_tx_msg.payload;
    status->state = (uint8_t)motion_get_state();
    /* Copy positions into local buffer first to avoid packed struct alignment */
    float pos_buf[AXIS_MAX];
    motion_get_positions(pos_buf);
    (void)memcpy(status->position, pos_buf, sizeof(pos_buf));
    /* velocity: not directly available from cached data, set to 0 */
    (void)memset(status->velocity, 0, sizeof(status->velocity));
    status->current_step = 0;  /* Updated by motion_task during execution */
    status->total_steps = 0;
    status->axis_mask = AXIS_MASK_PHASE1;

    ipc_finalize_and_send();
}

/**
 * @brief Send MSG_STATUS_TMC response (TMC260C-PA diagnostic data)
 */
static void ipc_send_status_tmc(void)
{
    ipc_prepare_header(MSG_STATUS_TMC, (uint16_t)sizeof(msg_status_tmc_t));

    const msg_status_tmc_t *tmc_status = tmc_get_status();
    (void)memcpy(s_tx_msg.payload, tmc_status, sizeof(msg_status_tmc_t));

    ipc_finalize_and_send();
}

/**
 * @brief Send MSG_STATUS_HEARTBEAT response
 */
static void ipc_send_heartbeat(void)
{
    ipc_prepare_header(MSG_STATUS_HEARTBEAT, (uint16_t)sizeof(msg_status_heartbeat_t));

    msg_status_heartbeat_t *hb = (msg_status_heartbeat_t *)s_tx_msg.payload;
    hb->uptime_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
    hb->state = (uint8_t)motion_get_state();
    hb->active_alarms = 0;  /* TODO: track alarm count */
    hb->watchdog_ok = 1;
    hb->axis_mask = AXIS_MASK_PHASE1;

    ipc_finalize_and_send();
}

/**
 * @brief Send MSG_STATUS_VERSION response
 */
static void ipc_send_version(void)
{
    ipc_prepare_header(MSG_STATUS_VERSION, (uint16_t)sizeof(msg_status_version_t));

    msg_status_version_t *ver = (msg_status_version_t *)s_tx_msg.payload;
    ver->major = 0;
    ver->minor = 1;
    ver->patch = 0;
    ver->reserved = 0;
    ver->build_timestamp = 0;  /* TODO: inject at build time via -D */

    ipc_finalize_and_send();
}

/* ──────────────────────────────────────────────
 * Message Dispatch: Motion Commands
 * ────────────────────────────────────────────── */

/**
 * @brief Dispatch a motion command to motion_task queue
 * @return true if enqueued successfully
 */
static bool ipc_dispatch_motion_cmd(const motion_cmd_t *cmd)
{
    QueueHandle_t q = motion_get_cmd_queue();
    if (q == NULL) {
        return false;
    }

    BaseType_t rc = xQueueSend(q, cmd, pdMS_TO_TICKS(IPC_MOTION_QUEUE_TIMEOUT_MS));
    return (rc == pdTRUE);
}

/**
 * @brief Handle MSG_MOTION_EXECUTE_BCODE
 */
static void ipc_handle_bcode(const ipc_message_t *rx_msg)
{
    if (rx_msg->header.payload_len < sizeof(uint16_t)) {
        ipc_send_nack(ERR_INVALID_PARAM);
        return;
    }

    motion_cmd_t cmd;
    (void)memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = MCMD_EXECUTE_BCODE;

    /* Copy payload into command (bounded by struct size) */
    uint32_t copy_len = rx_msg->header.payload_len;
    if (copy_len > sizeof(msg_motion_bcode_t)) {
        copy_len = sizeof(msg_motion_bcode_t);
    }
    (void)memcpy(&cmd.data.bcode, rx_msg->payload, copy_len);

    /* Validate step count */
    if (cmd.data.bcode.step_count == 0U ||
        cmd.data.bcode.step_count > BCODE_SEQUENCE_MAX_STEPS) {
        ipc_send_nack(ERR_MOTION_INVALID_BCODE);
        return;
    }

    if (!ipc_dispatch_motion_cmd(&cmd)) {
        ipc_send_nack(ERR_BUSY);
    }
}

/**
 * @brief Handle MSG_MOTION_JOG
 */
static void ipc_handle_jog(const ipc_message_t *rx_msg)
{
    if (rx_msg->header.payload_len < sizeof(msg_motion_jog_t)) {
        ipc_send_nack(ERR_INVALID_PARAM);
        return;
    }

    motion_cmd_t cmd;
    (void)memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = MCMD_JOG;
    (void)memcpy(&cmd.data.jog, rx_msg->payload, sizeof(msg_motion_jog_t));

    if (!ipc_dispatch_motion_cmd(&cmd)) {
        ipc_send_nack(ERR_BUSY);
    }
}

/**
 * @brief Handle MSG_MOTION_HOME
 */
static void ipc_handle_home(const ipc_message_t *rx_msg)
{
    motion_cmd_t cmd;
    (void)memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = MCMD_HOME;

    if (rx_msg->header.payload_len >= sizeof(msg_motion_home_t)) {
        (void)memcpy(&cmd.data.home, rx_msg->payload, sizeof(msg_motion_home_t));
    }

    if (!ipc_dispatch_motion_cmd(&cmd)) {
        ipc_send_nack(ERR_BUSY);
    }
}

/**
 * @brief Handle MSG_MOTION_STOP
 */
static void ipc_handle_stop(void)
{
    motion_cmd_t cmd;
    (void)memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = MCMD_STOP;

    /* Stop is high priority — use xQueueSendToFront */
    QueueHandle_t q = motion_get_cmd_queue();
    if (q != NULL) {
        (void)xQueueSendToFront(q, &cmd, 0);
    }
}

/**
 * @brief Handle MSG_MOTION_ESTOP — immediate, bypasses queue
 */
static void ipc_handle_estop(void)
{
    /* E-STOP is time-critical: invoke directly, do not queue */
    motion_estop();
}

/**
 * @brief Handle MSG_MOTION_SET_PARAM
 */
static void ipc_handle_set_param(const ipc_message_t *rx_msg)
{
    if (rx_msg->header.payload_len < sizeof(msg_motion_param_t)) {
        ipc_send_nack(ERR_INVALID_PARAM);
        return;
    }

    motion_cmd_t cmd;
    (void)memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = MCMD_SET_PARAM;
    (void)memcpy(&cmd.data.param, rx_msg->payload, sizeof(msg_motion_param_t));

    if (!ipc_dispatch_motion_cmd(&cmd)) {
        ipc_send_nack(ERR_BUSY);
    }
}

/**
 * @brief Handle MSG_MOTION_RESET
 */
static void ipc_handle_reset(void)
{
    motion_cmd_t cmd;
    (void)memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = MCMD_RESET;

    QueueHandle_t q = motion_get_cmd_queue();
    if (q != NULL) {
        (void)xQueueSendToFront(q, &cmd, 0);
    }
}

/**
 * @brief Handle MSG_MOTION_WIRE_DETECT
 */
static void ipc_handle_wire_detect(void)
{
    motion_cmd_t cmd;
    (void)memset(&cmd, 0, sizeof(cmd));
    cmd.cmd = MCMD_WIRE_DETECT;

    (void)ipc_dispatch_motion_cmd(&cmd);
}

/* ──────────────────────────────────────────────
 * Message Dispatch: Diagnostic Commands
 * ────────────────────────────────────────────── */

/* From tmc_poll_task.c */
extern tmc260c_t *tmc_get_driver(uint8_t axis);

/**
 * @brief Handle MSG_DIAG_TMC_READ
 *
 * For TMC260C-PA (STEP/DIR, SPI-configured):
 * - reg_addr is ignored; a live SPI poll is performed.
 * - reg_value in the response contains the raw 20-bit status datagram.
 */
static void ipc_handle_tmc_read(const ipc_message_t *rx_msg)
{
    if (rx_msg->header.payload_len < sizeof(msg_diag_tmc_t)) {
        ipc_send_nack(ERR_INVALID_PARAM);
        return;
    }

    const msg_diag_tmc_t *req = (const msg_diag_tmc_t *)rx_msg->payload;

    if (req->axis >= AXIS_MAX) {
        ipc_send_nack(ERR_INVALID_PARAM);
        return;
    }

    tmc260c_t *drv = tmc_get_driver(req->axis);
    if (drv == NULL) {
        ipc_send_nack(ERR_MOTION_AXIS_DISABLED);
        return;
    }

    /* Poll the driver to refresh status; returns raw 20-bit response */
    uint32_t value = tmc260c_read_status(drv);

    /* Send response: reg_addr echoed, reg_value = raw SPI response */
    ipc_prepare_header(MSG_DIAG_TMC_READ, (uint16_t)sizeof(msg_diag_tmc_t));
    msg_diag_tmc_t *resp = (msg_diag_tmc_t *)s_tx_msg.payload;
    resp->axis = req->axis;
    resp->reg_addr = req->reg_addr;
    resp->reg_value = value;
    ipc_finalize_and_send();
}

/**
 * @brief Handle MSG_DIAG_TMC_WRITE
 *
 * For TMC260C-PA:
 * - reg_value lower 20 bits = raw datagram to send (address tag in bits [19:17]).
 * - The 20-bit response (status) is returned in reg_value of the ACK.
 */
static void ipc_handle_tmc_write(const ipc_message_t *rx_msg)
{
    if (rx_msg->header.payload_len < sizeof(msg_diag_tmc_t)) {
        ipc_send_nack(ERR_INVALID_PARAM);
        return;
    }

    const msg_diag_tmc_t *req = (const msg_diag_tmc_t *)rx_msg->payload;

    if (req->axis >= AXIS_MAX) {
        ipc_send_nack(ERR_INVALID_PARAM);
        return;
    }

    tmc260c_t *drv = tmc_get_driver(req->axis);
    if (drv == NULL) {
        ipc_send_nack(ERR_MOTION_AXIS_DISABLED);
        return;
    }

    /* Send 20-bit datagram; response is the simultaneous SPI read-back */
    uint32_t response = tmc260c_spi_transfer(drv, req->reg_value & 0xFFFFFU);

    /* ACK: echo axis + reg_addr, reg_value = SPI response */
    ipc_prepare_header(MSG_DIAG_TMC_WRITE, (uint16_t)sizeof(msg_diag_tmc_t));
    msg_diag_tmc_t *resp = (msg_diag_tmc_t *)s_tx_msg.payload;
    resp->axis = req->axis;
    resp->reg_addr = req->reg_addr;
    resp->reg_value = response;
    ipc_finalize_and_send();
}

/**
 * @brief Handle MSG_DIAG_TMC_DUMP (dump all TMC5160 status)
 */
static void ipc_handle_tmc_dump(void)
{
    ipc_send_status_tmc();
}

/**
 * @brief Handle MSG_DIAG_GET_VERSION
 */
static void ipc_handle_get_version(void)
{
    ipc_send_version();
}

/* ──────────────────────────────────────────────
 * Message Validation
 * ────────────────────────────────────────────── */

/**
 * @brief Validate received IPC message
 * @param rx_msg Received message
 * @param received_len Total bytes received from transport
 * @return ERR_NONE if valid
 */
static error_code_t ipc_validate_message(const ipc_message_t *rx_msg,
                                          uint32_t received_len)
{
    /* Minimum: header size */
    if (received_len < sizeof(ipc_msg_header_t)) {
        return ERR_IPC_INVALID_MAGIC;
    }

    /* Magic check */
    if (rx_msg->header.magic != IPC_MAGIC) {
        return ERR_IPC_INVALID_MAGIC;
    }

    /* Message type validation */
    if (!ipc_msg_type_valid(rx_msg->header.msg_type)) {
        return ERR_IPC_INVALID_MSG_TYPE;
    }

    /* Payload length bounds */
    if (rx_msg->header.payload_len > IPC_MAX_PAYLOAD_SIZE) {
        return ERR_IPC_PAYLOAD_TOO_LARGE;
    }

    /* Check that we received enough bytes for header + payload */
    uint32_t expected_len = (uint32_t)sizeof(ipc_msg_header_t) + rx_msg->header.payload_len;
    if (received_len < expected_len) {
        return ERR_IPC_PAYLOAD_TOO_LARGE;
    }

    /* CRC-32 verification */
    if (!ipc_verify_crc32(rx_msg)) {
        return ERR_IPC_INVALID_MAGIC; /* CRC mismatch — use closest error code */
    }

    return ERR_NONE;
}

/* ──────────────────────────────────────────────
 * Message Router
 * ────────────────────────────────────────────── */

/**
 * @brief Route a validated message to the appropriate handler
 */
static void ipc_route_message(const ipc_message_t *rx_msg)
{
    switch (rx_msg->header.msg_type) {
    /* Motion commands */
    case MSG_MOTION_EXECUTE_BCODE:
        ipc_handle_bcode(rx_msg);
        break;

    case MSG_MOTION_JOG:
        ipc_handle_jog(rx_msg);
        break;

    case MSG_MOTION_HOME:
        ipc_handle_home(rx_msg);
        break;

    case MSG_MOTION_STOP:
        ipc_handle_stop();
        break;

    case MSG_MOTION_ESTOP:
        ipc_handle_estop();
        break;

    case MSG_MOTION_SET_PARAM:
        ipc_handle_set_param(rx_msg);
        break;

    case MSG_MOTION_RESET:
        ipc_handle_reset();
        break;

    case MSG_MOTION_WIRE_DETECT:
        ipc_handle_wire_detect();
        break;

    /* Diagnostic commands */
    case MSG_DIAG_TMC_READ:
        ipc_handle_tmc_read(rx_msg);
        break;

    case MSG_DIAG_TMC_WRITE:
        ipc_handle_tmc_write(rx_msg);
        break;

    case MSG_DIAG_TMC_DUMP:
        ipc_handle_tmc_dump();
        break;

    case MSG_DIAG_GET_VERSION:
        ipc_handle_get_version();
        break;

    /* Status requests: respond immediately */
    case MSG_STATUS_MOTION:
        ipc_send_status_motion();
        break;

    case MSG_STATUS_TMC:
        ipc_send_status_tmc();
        break;

    case MSG_STATUS_HEARTBEAT:
        ipc_send_heartbeat();
        break;

    default:
        ipc_send_nack(ERR_IPC_INVALID_MSG_TYPE);
        break;
    }
}

/* ──────────────────────────────────────────────
 * Task Entry Point
 * ────────────────────────────────────────────── */

/**
 * @brief IPC task: event-driven RPMsg message processor
 *
 * Blocks on rpmsg_hal_receive(). For each received message:
 * 1. Validates header (magic, type, payload length)
 * 2. Verifies CRC-32
 * 3. Routes to appropriate handler
 * 4. NACK on validation failure
 */
void ipc_task(void *params)
{
    (void)params;

    /* Initialize RPMsg transport */
    if (!rpmsg_hal_init()) {
        /* Fatal: cannot communicate with A53 */
        for (;;) {
            vTaskDelay(pdMS_TO_TICKS(1000));
        }
    }

    /* RX buffer (static) */
    static ipc_message_t s_rx_msg;
    uint32_t received_len = 0;

    for (;;) {
        /* Block until a message arrives (0 = infinite timeout) */
        bool got_msg = rpmsg_hal_receive(
            (uint8_t *)&s_rx_msg,
            sizeof(ipc_message_t),
            &received_len,
            0
        );

        if (!got_msg) {
            continue;
        }

        /* Validate message */
        error_code_t val_rc = ipc_validate_message(&s_rx_msg, received_len);
        if (val_rc != ERR_NONE) {
            ipc_send_nack(val_rc);
            continue;
        }

        /* Route to handler */
        ipc_route_message(&s_rx_msg);
    }
}
