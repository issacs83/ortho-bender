/**
 * @file rpmsg_client.h
 * @brief RPMsg IPC client for A53 -> M7 communication
 *
 * IEC 62304 SW Class: B
 */

#ifndef RPMSG_CLIENT_H
#define RPMSG_CLIENT_H

#include <cstdint>
#include <functional>
#include <string>

extern "C" {
#include "ipc_protocol.h"
}

namespace ortho_bender {

/**
 * @brief Callback type for received IPC messages
 */
using IpcCallback = std::function<void(const ipc_message_t&)>;

/**
 * @brief RPMsg IPC client
 *
 * Provides A53-side interface to communicate with M7 firmware via RPMsg.
 * Uses /dev/rpmsgX device nodes exposed by the remoteproc/rpmsg kernel driver.
 */
class RpmsgClient {
public:
    RpmsgClient();
    ~RpmsgClient();

    /**
     * @brief Open RPMsg endpoint
     * @param device RPMsg device path (e.g., "/dev/rpmsg0")
     * @return true on success
     */
    bool open(const std::string& device = "/dev/rpmsg0");

    /**
     * @brief Close RPMsg endpoint
     */
    void close();

    /**
     * @brief Check if endpoint is connected
     */
    bool is_connected() const;

    /**
     * @brief Send IPC message to M7
     */
    bool send(ipc_msg_type_t type, const void* payload, uint16_t payload_len);

    /**
     * @brief Send B-code execution command
     */
    bool send_bcode(const msg_motion_bcode_t& bcode);

    /**
     * @brief Send jog command
     */
    bool send_jog(const msg_motion_jog_t& jog);

    /**
     * @brief Send home command
     */
    bool send_home();

    /**
     * @brief Send E-STOP command
     */
    bool send_estop();

    /**
     * @brief Register callback for incoming messages
     */
    void on_message(IpcCallback callback);

    /**
     * @brief Poll for incoming messages (non-blocking)
     * @param timeout_ms Timeout in milliseconds (0 = non-blocking)
     * @return true if message was received and dispatched
     */
    bool poll(uint32_t timeout_ms = 0);

private:
    int         fd_;
    uint32_t    sequence_;
    IpcCallback callback_;

    ipc_msg_header_t build_header(ipc_msg_type_t type, uint16_t payload_len);
};

} // namespace ortho_bender

#endif /* RPMSG_CLIENT_H */
