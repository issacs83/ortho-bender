/*
 * motor_sim.cpp - B2 Motor Controller Simulator
 *
 * Creates a PTY (virtual serial port) that simulates the B2 motor controller
 * board protocol. Use with kc_test when no physical hardware is connected.
 *
 * Usage:
 *   ./motor_sim                    # auto-create PTY
 *   ./motor_sim --speed-factor 10  # 10x faster motion simulation
 *
 * Then run kc_test with the printed PTY slave path:
 *   ./kc_test_motor_only           # auto-detect won't work with PTY
 *   # Instead, modify mcFindComm or use mcConnectComm directly
 *
 * Protocol: STX(0x5B) | CMD | DATA... | CRC16(2B) | ETX(0x5D)
 * Response: STX(0x5B) | CMD+0x10 | DATA... | CRC16(2B) | ETX(0x5D)
 */

#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <unistd.h>
#include <fcntl.h>
#include <pty.h>
#include <termios.h>
#include <signal.h>
#include <sys/select.h>
#include <chrono>
#include <atomic>
#include <thread>
#include <mutex>
#include <string>

/* ── Protocol Constants (from stub.h) ── */

#define STX             0x5B
#define ETX             0x5D

#define CMD_INIT            0x50
#define CMD_SETTORQUE       0x51
#define CMD_SETRESOLUTION   0x52
#define CMD_MOVEVEL         0x53
#define CMD_MOVEABS         0x54
#define CMD_STOP            0x55
#define CMD_STOPDECL        0x56
#define CMD_SETBRIGHTNESS   0x57
#define CMD_SETSTALLGUARD   0x58
#define CMD_WRITE           0x59

#define CMD_GETCONSTATE     0xA1
#define CMD_GETSTATE        0xA2
#define CMD_GETPOSITION     0xA3
#define CMD_GETERROR        0xA4
#define CMD_GETSENSORSTATE  0xA5
#define CMD_READ            0xA6
#define CMD_HELLO           0xA7
#define CMD_GETVERSION      0xA9

#define MID_BENDER  0x01
#define MID_FEEDER  0x02
#define MID_LIFTER  0x03
#define MID_CUTTER  0x04

#define MAX_FRAME_SIZE  256
#define MAX_MOTORS      4

/* ── CRC16 (Modbus) ── */

static const uint16_t TABLE_CRCVALUE[] = {
    0X0000, 0XC0C1, 0XC181, 0X0140, 0XC301, 0X03C0, 0X0280, 0XC241,
    0XC601, 0X06C0, 0X0780, 0XC741, 0X0500, 0XC5C1, 0XC481, 0X0440,
    0XCC01, 0X0CC0, 0X0D80, 0XCD41, 0X0F00, 0XCFC1, 0XCE81, 0X0E40,
    0X0A00, 0XCAC1, 0XCB81, 0X0B40, 0XC901, 0X09C0, 0X0880, 0XC841,
    0XD801, 0X18C0, 0X1980, 0XD941, 0X1B00, 0XDBC1, 0XDA81, 0X1A40,
    0X1E00, 0XDEC1, 0XDF81, 0X1F40, 0XDD01, 0X1DC0, 0X1C80, 0XDC41,
    0X1400, 0XD4C1, 0XD581, 0X1540, 0XD701, 0X17C0, 0X1680, 0XD641,
    0XD201, 0X12C0, 0X1380, 0XD341, 0X1100, 0XD1C1, 0XD081, 0X1040,
    0XF001, 0X30C0, 0X3180, 0XF141, 0X3300, 0XF3C1, 0XF281, 0X3240,
    0X3600, 0XF6C1, 0XF781, 0X3740, 0XF501, 0X35C0, 0X3480, 0XF441,
    0X3C00, 0XFCC1, 0XFD81, 0X3D40, 0XFF01, 0X3FC0, 0X3E80, 0XFE41,
    0XFA01, 0X3AC0, 0X3B80, 0XFB41, 0X3900, 0XF9C1, 0XF881, 0X3840,
    0X2800, 0XE8C1, 0XE981, 0X2940, 0XEB01, 0X2BC0, 0X2A80, 0XEA41,
    0XEE01, 0X2EC0, 0X2F80, 0XEF41, 0X2D00, 0XEDC1, 0XEC81, 0X2C40,
    0XE401, 0X24C0, 0X2580, 0XE541, 0X2700, 0XE7C1, 0XE681, 0X2640,
    0X2200, 0XE2C1, 0XE381, 0X2340, 0XE101, 0X21C0, 0X2080, 0XE041,
    0XA001, 0X60C0, 0X6180, 0XA141, 0X6300, 0XA3C1, 0XA281, 0X6240,
    0X6600, 0XA6C1, 0XA781, 0X6740, 0XA501, 0X65C0, 0X6480, 0XA441,
    0X6C00, 0XACC1, 0XAD81, 0X6D40, 0XAF01, 0X6FC0, 0X6E80, 0XAE41,
    0XAA01, 0X6AC0, 0X6B80, 0XAB41, 0X6900, 0XA9C1, 0XA881, 0X6840,
    0X7800, 0XB8C1, 0XB981, 0X7940, 0XBB01, 0X7BC0, 0X7A80, 0XBA41,
    0XBE01, 0X7EC0, 0X7F80, 0XBF41, 0X7D00, 0XBDC1, 0XBC81, 0X7C40,
    0XB401, 0X74C0, 0X7580, 0XB541, 0X7700, 0XB7C1, 0XB681, 0X7640,
    0X7200, 0XB2C1, 0XB381, 0X7340, 0XB101, 0X71C0, 0X7080, 0XB041,
    0X5000, 0X90C1, 0X9181, 0X5140, 0X9301, 0X53C0, 0X5280, 0X9241,
    0X9601, 0X56C0, 0X5780, 0X9741, 0X5500, 0X95C1, 0X9481, 0X5440,
    0X9C01, 0X5CC0, 0X5D80, 0X9D41, 0X5F00, 0X9FC1, 0X9E81, 0X5E40,
    0X5A00, 0X9AC1, 0X9B81, 0X5B40, 0X9901, 0X59C0, 0X5880, 0X9841,
    0X8801, 0X48C0, 0X4980, 0X8941, 0X4B00, 0X8BC1, 0X8A81, 0X4A40,
    0X4E00, 0X8EC1, 0X8F81, 0X4F40, 0X8D01, 0X4DC0, 0X4C80, 0X8C41,
    0X4400, 0X84C1, 0X8581, 0X4540, 0X8701, 0X47C0, 0X4680, 0X8641,
    0X8201, 0X42C0, 0X4380, 0X8341, 0X4100, 0X81C1, 0X8081, 0X4040
};

static uint16_t calc_crc(const uint8_t *buf, size_t len)
{
    uint16_t crc = 0xFFFF;
    while (len--) {
        uint8_t temp = crc ^ *buf++;
        crc >>= 8;
        crc ^= TABLE_CRCVALUE[temp];
    }
    return crc;
}

/* ── Motor State ── */

struct motor_state_t {
    int32_t     position;       /* current position in steps */
    int32_t     target;         /* target position */
    int         speed;          /* steps per second */
    uint8_t     resolution;     /* microstep resolution index */
    uint8_t     torque;         /* torque limit (0-31) */
    uint8_t     sg_threshold;   /* StallGuard threshold */
    bool        moving;         /* currently in motion */
    uint8_t     direction;      /* 0=CW, 1=CCW */
    bool        homing;         /* in homing (init) sequence */
    std::chrono::steady_clock::time_point move_start;
};

static motor_state_t g_motors[MAX_MOTORS];
static std::recursive_mutex g_motor_mutex;
static std::atomic<bool> g_running{true};
static float g_speed_factor = 1.0f;

/* Simulated sensor states: [bending, feed0, feed1, retract, cutter] */
static bool g_sensors[5] = {true, false, false, true, true};

/* Simulated EEPROM (3KB) */
static uint8_t g_eeprom[0xC00];

static const char *motor_name(uint8_t id)
{
    switch (id) {
    case MID_BENDER: return "BENDER";
    case MID_FEEDER: return "FEEDER";
    case MID_LIFTER: return "LIFTER";
    case MID_CUTTER: return "CUTTER";
    default:         return "UNKNOWN";
    }
}

static int motor_index(uint8_t id)
{
    if (id >= 1 && id <= 4) return id - 1;
    return -1;
}

static int microstep_value(uint8_t res)
{
    /* resolution register: 256 >> res */
    if (res > 8) res = 8;
    return 256 >> res;
}

/* Update motor positions based on elapsed time */
static void update_motors()
{
    std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
    auto now = std::chrono::steady_clock::now();

    for (int i = 0; i < MAX_MOTORS; i++) {
        motor_state_t &m = g_motors[i];
        if (!m.moving) continue;

        auto elapsed = std::chrono::duration<double>(now - m.move_start).count();
        double steps_moved = elapsed * m.speed * g_speed_factor;

        int32_t delta = m.target - m.position;
        int32_t abs_delta = abs(delta);

        if (steps_moved >= abs_delta) {
            /* Motion complete */
            m.position = m.target;
            m.moving = false;
        } else {
            /* Still moving */
            if (delta > 0)
                m.position = m.position + static_cast<int32_t>(steps_moved);
            else
                m.position = m.position - static_cast<int32_t>(steps_moved);
            m.move_start = now;
        }
    }
}

/* ── Frame Builder ── */

static int build_reply(uint8_t *out, uint8_t cmd_ack, const uint8_t *data, int data_len)
{
    int idx = 0;
    out[idx++] = STX;
    out[idx++] = cmd_ack;
    for (int i = 0; i < data_len; i++)
        out[idx++] = data[i];

    uint16_t crc = calc_crc(out, idx);
    out[idx++] = (crc >> 8) & 0xFF;
    out[idx++] = crc & 0xFF;
    out[idx++] = ETX;
    return idx;
}

/* ── Command Handlers ── */

static int handle_hello(uint8_t *out)
{
    printf("[SIM] HELLO\n");
    return build_reply(out, CMD_HELLO + 0x10, nullptr, 0);
}

static int handle_getversion(uint8_t *out)
{
    printf("[SIM] GET_VERSION\n");
    uint8_t ver[5] = {'S', 'I', 'M', '0', '1'};
    return build_reply(out, CMD_GETVERSION + 0x10, ver, 5);
}

static int handle_init(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    uint8_t dir = data[1];
    int speed = (data[2] << 16) | (data[3] << 8) | data[4];

    printf("[SIM] INIT %s dir=%s speed=%d\n", motor_name(id),
           dir == 0 ? "CW" : "CCW", speed);

    int idx = motor_index(id);
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        motor_state_t &m = g_motors[idx];
        m.homing = true;
        m.moving = true;
        m.direction = dir;
        m.speed = speed;
        /* Simulate homing: move to position 0 */
        m.target = 0;
        m.move_start = std::chrono::steady_clock::now();
        /* Immediately complete homing for simulator */
        m.position = 0;
        m.moving = false;
        m.homing = false;
    }

    return build_reply(out, CMD_INIT + 0x10, data, 5);
}

static int handle_movevel(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    uint8_t dir = data[1];
    uint32_t steps = (data[2] << 24) | (data[3] << 16) | (data[4] << 8) | data[5];
    int speedacc = (data[6] << 16) | (data[7] << 8) | data[8];
    int speedmax = (data[9] << 16) | (data[10] << 8) | data[11];
    int speeddec = (data[12] << 16) | (data[13] << 8) | data[14];

    printf("[SIM] MOVEVEL %s dir=%s steps=%u vmax=%d acc=%d dec=%d\n",
           motor_name(id), dir == 0 ? "CW" : "CCW", steps, speedmax, speedacc, speeddec);

    int idx = motor_index(id);
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        motor_state_t &m = g_motors[idx];
        m.moving = true;
        m.direction = dir;
        m.speed = speedmax > 0 ? speedmax : 1;
        if (dir == 0)
            m.target = m.position + static_cast<int32_t>(steps);
        else
            m.target = m.position - static_cast<int32_t>(steps);
        m.move_start = std::chrono::steady_clock::now();
    }

    return build_reply(out, CMD_MOVEVEL + 0x10, data, 15);
}

static int handle_moveabs(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    uint8_t dir = data[1];
    uint32_t steps = (data[2] << 24) | (data[3] << 16) | (data[4] << 8) | data[5];
    int speedacc = (data[6] << 16) | (data[7] << 8) | data[8];
    int speedmax = (data[9] << 16) | (data[10] << 8) | data[11];
    int speeddec = (data[12] << 16) | (data[13] << 8) | data[14];

    int32_t target_pos = (dir == 0) ? static_cast<int32_t>(steps) : -static_cast<int32_t>(steps);

    printf("[SIM] MOVEABS %s dir=%s steps=%u (target=%d) vmax=%d\n",
           motor_name(id), dir == 0 ? "CW" : "CCW", steps, target_pos, speedmax);

    int idx = motor_index(id);
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        motor_state_t &m = g_motors[idx];
        m.moving = true;
        m.direction = dir;
        m.speed = speedmax > 0 ? speedmax : 1;
        m.target = target_pos;
        m.move_start = std::chrono::steady_clock::now();
    }

    return build_reply(out, CMD_MOVEABS + 0x10, data, 15);
}

static int handle_stop(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    printf("[SIM] STOP %s\n", motor_name(id));

    int idx = motor_index(id);
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        g_motors[idx].moving = false;
        g_motors[idx].target = g_motors[idx].position;
    }

    return build_reply(out, CMD_STOP + 0x10, data, 1);
}

static int handle_stopdecl(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    printf("[SIM] STOP_DECL %s dec=%d\n", motor_name(id), data[1]);

    int idx = motor_index(id);
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        g_motors[idx].moving = false;
        g_motors[idx].target = g_motors[idx].position;
    }

    uint8_t reply_data[2] = {id, 0x00};
    return build_reply(out, CMD_STOPDECL + 0x10, reply_data, 2);
}

static int handle_getstate(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    int idx = motor_index(id);

    uint8_t state = 0x00; /* 0=stopped */
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        update_motors();
        if (g_motors[idx].moving)
            state = 0x01; /* moving */
    }

    uint8_t reply_data[2] = {id, state};
    return build_reply(out, CMD_GETSTATE + 0x10, reply_data, 2);
}

static int handle_getconstate(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    uint8_t reply_data[2] = {id, 0x01}; /* always connected */
    return build_reply(out, CMD_GETCONSTATE + 0x10, reply_data, 2);
}

static int handle_geterror(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    int idx = motor_index(id);

    uint8_t err = 0x00;
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        update_motors();
        if (!g_motors[idx].moving)
            err = 0x80; /* bit7 = stopped */
    }

    uint8_t reply_data[2] = {id, err};
    return build_reply(out, CMD_GETERROR + 0x10, reply_data, 2);
}

static int handle_getposition(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    int idx = motor_index(id);

    int32_t pos = 0;
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        update_motors();
        pos = g_motors[idx].position;
    }

    uint8_t sign = (pos < 0) ? 1 : 0;
    uint32_t abs_pos = static_cast<uint32_t>(abs(pos));

    uint8_t reply_data[6];
    reply_data[0] = id;
    reply_data[1] = sign;
    reply_data[2] = (abs_pos >> 24) & 0xFF;
    reply_data[3] = (abs_pos >> 16) & 0xFF;
    reply_data[4] = (abs_pos >> 8) & 0xFF;
    reply_data[5] = abs_pos & 0xFF;

    return build_reply(out, CMD_GETPOSITION + 0x10, reply_data, 6);
}

static int handle_settorque(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    uint8_t torque = data[1];
    printf("[SIM] SET_TORQUE %s torque=0x%02X\n", motor_name(id), torque);

    int idx = motor_index(id);
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        g_motors[idx].torque = torque;
    }

    return build_reply(out, CMD_SETTORQUE + 0x10, data, 2);
}

static int handle_setresolution(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    uint8_t res = data[1];
    printf("[SIM] SET_RESOLUTION %s res=%d (ustep=%d)\n",
           motor_name(id), res, microstep_value(res));

    int idx = motor_index(id);
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        g_motors[idx].resolution = res;
    }

    return build_reply(out, CMD_SETRESOLUTION + 0x10, data, 2);
}

static int handle_setstallguard(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    uint8_t thr = data[1];
    printf("[SIM] SET_STALLGUARD %s threshold=%d\n", motor_name(id), thr);

    int idx = motor_index(id);
    if (idx >= 0) {
        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        g_motors[idx].sg_threshold = thr;
    }

    return build_reply(out, CMD_SETSTALLGUARD + 0x10, data, 2);
}

static int handle_setbrightness(const uint8_t *data, uint8_t *out)
{
    uint8_t id = data[0];
    printf("[SIM] SET_LIGHT id=%d R=%d G=%d B=%d\n", id, data[1], data[2], data[3]);
    return build_reply(out, CMD_SETBRIGHTNESS + 0x10, data, 4);
}

static int handle_getsensorstate(uint8_t *out)
{
    uint8_t reply_data[5];
    reply_data[0] = g_sensors[0] ? 0 : 1; /* bending (inverted in client) */
    reply_data[1] = g_sensors[1] ? 1 : 0; /* feed0 */
    reply_data[2] = g_sensors[2] ? 1 : 0; /* feed1 */
    reply_data[3] = g_sensors[3] ? 0 : 1; /* retract (inverted) */
    reply_data[4] = g_sensors[4] ? 0 : 1; /* cutter (inverted) */
    printf("[SIM] GET_SENSOR_STATE B=%d F0=%d F1=%d R=%d C=%d\n",
           g_sensors[0], g_sensors[1], g_sensors[2], g_sensors[3], g_sensors[4]);
    return build_reply(out, CMD_GETSENSORSTATE + 0x10, reply_data, 5);
}

static int handle_write(const uint8_t *data, uint8_t *out)
{
    uint16_t addr = (data[0] << 8) | data[1];
    uint8_t size = data[2];
    if (size > 100) size = 100;
    if (addr + size <= sizeof(g_eeprom))
        memcpy(&g_eeprom[addr], &data[3], size);
    printf("[SIM] WRITE addr=0x%04X size=%d\n", addr, size);
    uint8_t reply_data[1] = {0x00};
    return build_reply(out, CMD_WRITE + 0x10, reply_data, 1);
}

static int handle_read(const uint8_t *data, uint8_t *out)
{
    uint16_t addr = (data[0] << 8) | data[1];
    uint8_t size = data[2];
    if (size > 100) size = 100;
    printf("[SIM] READ addr=0x%04X size=%d\n", addr, size);

    uint8_t reply_data[103];
    reply_data[0] = data[0];
    reply_data[1] = data[1];
    reply_data[2] = size;
    if (addr + size <= sizeof(g_eeprom))
        memcpy(&reply_data[3], &g_eeprom[addr], size);
    else
        memset(&reply_data[3], 0, size);

    return build_reply(out, CMD_READ + 0x10, reply_data, 3 + size);
}

/* ── Frame Parser & Dispatcher ── */

static int process_frame(const uint8_t *frame, int frame_len, uint8_t *out)
{
    if (frame_len < 5) return 0; /* minimum: STX CMD CRC16 ETX */
    if (frame[0] != STX || frame[frame_len - 1] != ETX) return 0;

    uint8_t cmd = frame[1];
    const uint8_t *data = &frame[2];
    int data_len = frame_len - 5; /* subtract STX, CMD, CRC16(2), ETX */

    /* Verify CRC */
    uint16_t rx_crc = (frame[frame_len - 3] << 8) | frame[frame_len - 2];
    uint16_t calc = calc_crc(frame, frame_len - 3);
    if (rx_crc != calc) {
        printf("[SIM] CRC mismatch: rx=0x%04X calc=0x%04X\n", rx_crc, calc);
        /* Respond anyway for compatibility — B2 firmware may differ */
    }

    switch (cmd) {
    case CMD_HELLO:         return handle_hello(out);
    case CMD_GETVERSION:    return handle_getversion(out);
    case CMD_INIT:          return handle_init(data, out);
    case CMD_MOVEVEL:       return handle_movevel(data, out);
    case CMD_MOVEABS:       return handle_moveabs(data, out);
    case CMD_STOP:          return handle_stop(data, out);
    case CMD_STOPDECL:      return handle_stopdecl(data, out);
    case CMD_GETSTATE:      return handle_getstate(data, out);
    case CMD_GETCONSTATE:   return handle_getconstate(data, out);
    case CMD_GETERROR:      return handle_geterror(data, out);
    case CMD_GETPOSITION:   return handle_getposition(data, out);
    case CMD_SETTORQUE:     return handle_settorque(data, out);
    case CMD_SETRESOLUTION: return handle_setresolution(data, out);
    case CMD_SETSTALLGUARD: return handle_setstallguard(data, out);
    case CMD_SETBRIGHTNESS: return handle_setbrightness(data, out);
    case CMD_GETSENSORSTATE: return handle_getsensorstate(out);
    case CMD_WRITE:         return handle_write(data, out);
    case CMD_READ:          return handle_read(data, out);
    default:
        printf("[SIM] Unknown command: 0x%02X\n", cmd);
        return 0;
    }
}

/* ── Status Display Thread ── */

static void status_thread_func()
{
    while (g_running.load()) {
        std::this_thread::sleep_for(std::chrono::seconds(5));
        if (!g_running.load()) break;

        std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
        update_motors();

        printf("\n[SIM] === Motor Status ===\n");
        for (int i = 0; i < MAX_MOTORS; i++) {
            const motor_state_t &m = g_motors[i];
            printf("  %s: pos=%d target=%d %s\n",
                   motor_name(i + 1), m.position, m.target,
                   m.moving ? "MOVING" : "IDLE");
        }
        printf("[SIM] =====================\n\n");
    }
}

/* ── Signal Handler ── */

static void signal_handler(int)
{
    g_running.store(false);
}

/* ── Main ── */

int main(int argc, char *argv[])
{
    /* Parse arguments */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--speed-factor") == 0 && i + 1 < argc) {
            g_speed_factor = strtof(argv[++i], nullptr);
            if (g_speed_factor <= 0) g_speed_factor = 1.0f;
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            printf("Usage: %s [--speed-factor N]\n", argv[0]);
            printf("  --speed-factor N   Motion simulation speed multiplier (default: 1.0)\n");
            return 0;
        }
    }

    /* Line-buffered stdout for logging */
    setvbuf(stdout, nullptr, _IOLBF, 0);

    printf("=== B2 Motor Controller Simulator ===\n");
    printf("Speed factor: %.1fx\n\n", g_speed_factor);

    /* Initialize motors */
    memset(g_motors, 0, sizeof(g_motors));
    for (int i = 0; i < MAX_MOTORS; i++) {
        g_motors[i].resolution = 1;
        g_motors[i].torque = 16;
        g_motors[i].sg_threshold = 8;
    }
    memset(g_eeprom, 0xFF, sizeof(g_eeprom));

    /* Create PTY pair using openpty() for proper slave setup */
    int master_fd, slave_fd;
    char slave_name[256];

    if (openpty(&master_fd, &slave_fd, slave_name, nullptr, nullptr) < 0) {
        perror("openpty");
        return 1;
    }

    /* Configure slave for raw mode (clients will reconfigure, but set sane defaults) */
    struct termios tty;
    tcgetattr(slave_fd, &tty);
    cfmakeraw(&tty);
    cfsetispeed(&tty, B19200);
    cfsetospeed(&tty, B19200);
    tcsetattr(slave_fd, TCSANOW, &tty);

    /* Close slave fd — clients will open it themselves */
    close(slave_fd);

    printf("PTY slave device: %s\n", slave_name);
    printf("Connect kc_test to this device.\n\n");
    printf("Example:\n");
    printf("  # In kc_test, use: mcConnectComm(\"%s\")\n", slave_name);
    printf("  # Or create symlink: ln -sf %s /dev/ttyUSB_SIM\n\n", slave_name);

    /* Also create a convenient symlink */
    unlink("/tmp/b2_motor_sim");
    if (symlink(slave_name, "/tmp/b2_motor_sim") == 0)
        printf("Symlink created: /tmp/b2_motor_sim -> %s\n\n", slave_name);

    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    /* Start status display thread */
    std::thread status_th(status_thread_func);

    printf("[SIM] Waiting for connection...\n");

    /* Main loop: read frames from PTY and respond */
    uint8_t rx_buf[MAX_FRAME_SIZE];
    int rx_len = 0;
    bool in_frame = false;

    while (g_running.load()) {
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(master_fd, &fds);

        struct timeval tv;
        tv.tv_sec = 1;
        tv.tv_usec = 0;

        int ret = select(master_fd + 1, &fds, nullptr, nullptr, &tv);
        if (ret < 0) {
            if (g_running.load()) perror("select");
            break;
        }
        if (ret == 0) {
            /* Timeout — update motor positions */
            std::lock_guard<std::recursive_mutex> lock(g_motor_mutex);
            update_motors();
            continue;
        }

        uint8_t byte;
        ssize_t n = read(master_fd, &byte, 1);
        if (n <= 0) continue;

        if (byte == STX) {
            /* Start of new frame */
            rx_len = 0;
            in_frame = true;
        }

        if (in_frame) {
            if (rx_len < MAX_FRAME_SIZE) {
                rx_buf[rx_len++] = byte;
            } else {
                /* Frame too large, reset */
                in_frame = false;
                rx_len = 0;
                continue;
            }

            if (byte == ETX && rx_len >= 5) {
                /* Complete frame received */
                uint8_t reply[MAX_FRAME_SIZE];
                int reply_len = process_frame(rx_buf, rx_len, reply);

                if (reply_len > 0) {
                    write(master_fd, reply, reply_len);
                }

                in_frame = false;
                rx_len = 0;
            }
        }
    }

    printf("\n[SIM] Shutting down...\n");
    g_running.store(false);
    status_th.join();
    unlink("/tmp/b2_motor_sim");
    close(master_fd);

    return 0;
}
