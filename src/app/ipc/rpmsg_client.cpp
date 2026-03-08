/**
 * @file rpmsg_client.cpp
 * @brief RPMsg IPC client implementation
 *
 * IEC 62304 SW Class: B
 */

#include "rpmsg_client.h"

#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <cstddef>
#include <cstring>
#include <ctime>

namespace ortho_bender {

RpmsgClient::RpmsgClient()
    : fd_(-1)
    , sequence_(0)
    , callback_(nullptr)
{
}

RpmsgClient::~RpmsgClient()
{
    close();
}

bool RpmsgClient::open(const std::string& device)
{
    fd_ = ::open(device.c_str(), O_RDWR);
    return (fd_ >= 0);
}

void RpmsgClient::close()
{
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
}

bool RpmsgClient::is_connected() const
{
    return (fd_ >= 0);
}

ipc_msg_header_t RpmsgClient::build_header(ipc_msg_type_t type, uint16_t payload_len)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);

    ipc_msg_header_t hdr{};
    hdr.magic       = IPC_MAGIC;
    hdr.msg_type    = static_cast<uint16_t>(type);
    hdr.payload_len = payload_len;
    hdr.sequence    = sequence_++;
    hdr.timestamp_us = static_cast<uint64_t>(ts.tv_sec) * 1000000ULL
                     + static_cast<uint64_t>(ts.tv_nsec / 1000UL);
    hdr.crc32       = 0; /* computed after payload is copied into message */

    return hdr;
}

bool RpmsgClient::send(ipc_msg_type_t type, const void* payload, uint16_t payload_len)
{
    if (!is_connected() || payload_len > IPC_MAX_PAYLOAD_SIZE) {
        return false;
    }

    ipc_message_t msg{};
    msg.header = build_header(type, payload_len);

    if (payload && payload_len > 0) {
        std::memcpy(msg.payload, payload, payload_len);
    }

    msg.header.crc32 = ipc_compute_crc32(&msg);

    ssize_t written = ::write(fd_, &msg,
        sizeof(ipc_msg_header_t) + payload_len);

    return (written > 0);
}

bool RpmsgClient::send_bcode(const msg_motion_bcode_t& bcode)
{
    if (bcode.step_count > BCODE_SEQUENCE_MAX_STEPS) {
        return false;
    }

    uint16_t len = static_cast<uint16_t>(
        offsetof(msg_motion_bcode_t, steps) +
        bcode.step_count * sizeof(bcode_step_t));
    return send(MSG_MOTION_EXECUTE_BCODE, &bcode, len);
}

bool RpmsgClient::send_jog(const msg_motion_jog_t& jog)
{
    return send(MSG_MOTION_JOG, &jog, sizeof(msg_motion_jog_t));
}

bool RpmsgClient::send_home()
{
    return send(MSG_MOTION_HOME, nullptr, 0);
}

bool RpmsgClient::send_estop()
{
    return send(MSG_MOTION_ESTOP, nullptr, 0);
}

void RpmsgClient::on_message(IpcCallback callback)
{
    callback_ = callback;
}

bool RpmsgClient::poll(uint32_t timeout_ms)
{
    if (!is_connected()) {
        return false;
    }

    struct pollfd pfd{};
    pfd.fd = fd_;
    pfd.events = POLLIN;

    int ret = ::poll(&pfd, 1, static_cast<int>(timeout_ms));
    if (ret <= 0) {
        return false;
    }

    ipc_message_t msg{};
    ssize_t bytes = ::read(fd_, &msg, sizeof(msg));

    if (bytes < static_cast<ssize_t>(sizeof(ipc_msg_header_t))) {
        return false;
    }

    if (msg.header.magic != IPC_MAGIC) {
        return false;
    }

    if (!ipc_msg_type_valid(msg.header.msg_type)) {
        return false;
    }

    if (msg.header.payload_len > IPC_MAX_PAYLOAD_SIZE) {
        return false;
    }

    if (!ipc_verify_crc32(&msg)) {
        return false;
    }

    if (callback_) {
        callback_(msg);
        return true;
    }

    return false;
}

} // namespace ortho_bender
