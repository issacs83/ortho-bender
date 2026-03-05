/*
 * stub.cpp - Motor control implementation (Linux port)
 * Original: YOAT Corporation B2 TEST PROGRAM
 * Changes: Sleep→chrono, QPC→steady_clock, COM→/dev/ttyUSB|ACM, sprintf_s→snprintf
 */
#include "stub.h"
#include <thread>
#include <mutex>
#include <queue>
#include <atomic>
#include <vector>
#include <cstdio>

//#define SHOW_DEBUGMSG

LARGE_INTEGER               g_frequency;
serial::Serial*             g_comm = NULL;
static int                  g_motorres[4] = { 16, 16, 16, 16 };

static std::atomic<bool>    g_lightheartbeat_flag;
static std::thread*         g_lightheartbeatthread = NULL;
static std::mutex           g_comm_mutex;


//-------------------------------------- MOTOR COMMAND -----------------------------------------------

const unsigned short TABLE_CRCVALUE[] =
{
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

unsigned short CalcCRC(unsigned char* pDataBuffer, unsigned long usDataLen)
{
    unsigned char nTemp;
    unsigned short wCRCWord = 0xFFFF;
    while (usDataLen--)
    {
        nTemp = wCRCWord ^ *(pDataBuffer++);
        wCRCWord >>= 8;
        wCRCWord ^= TABLE_CRCVALUE[nTemp];
    }
    return wCRCWord;
}

int sendcmd(uint8_t cmd, uint8_t* data, int size)
{
    if (!g_comm)
        return E_NOTCON;

    try
    {
        unsigned short  crc_value = 0;

        std::vector<uint8_t> cmdvec;

        cmdvec.push_back(0x5b);  // STX
        cmdvec.push_back(cmd);
        int k = 0;
        for (; k < size; k++)
            cmdvec.push_back(data[k]);

        crc_value = CalcCRC(&cmdvec[0], k + 2);
        cmdvec.push_back((crc_value >> 8 & 0xff));
        cmdvec.push_back((crc_value & 0xff));
        cmdvec.push_back(0x5d);  // ETX

        int r = g_comm->write(cmdvec);
        return r;
    }
    catch (serial::IOException& e)
    {
        mcCloseComm();
        printf("sendcmd exception: %s\n", e.what());
        return E_CLOSED;
    }

    return E_CMD;
}

void debug_reply(const char* title, uint8_t* reply, int len)
{
    printf("%s ACK : ", title);
    for (int k = 0; k < len; k++)
    {
        printf("%02x ", reply[k]);
    }
    printf("\n");
}

int getack(uint8_t* reply, int ps, const char* name)
{
    if (!g_comm)
        return E_NOTCON;

    try
    {
        int len = 0;
        // wait for 1s max
        for (int retry = 0; retry < 100; retry++)
        {
            len = g_comm->available();
            if (len == ps)
                break;
            if (len < ps)
            {
                Sleep(10);
                continue;
            }
        }

        if (0 == len)
            return E_ACK;
        if (len > ps)
            return E_OVERFLOW;

        int readbytes = g_comm->read(reply, ps);
        if (reply[ACKC] == CMD_PROTOCOLERROR)
        {
            printf("*PROTOCOL ERROR* Func: %s, Reason: ", name);
            if (reply[ACKD] == 0x01)
                printf("Time out\n");
            else if (reply[ACKD] == 0x02)
                printf("BCC error\n");
            else if (reply[ACKD] == 0x03)
                printf("Length mismatch\n");
            return E_PROTOCOL;
        }

        return readbytes;
    }
    catch (serial::IOException& e)
    {
        mcCloseComm();
        printf("getack exception: %s\n", e.what());
        return E_CLOSED;
    }

    return E_CMD;
}


bool mcMoveVel2(uint8_t id, uint8_t dir, unsigned int step, int speed)
{
    uint8_t data[15];
    data[0] = id;
    data[1] = dir;
    data[2] = (0xff000000 & step) >> 24;
    data[3] = (0x00ff0000 & step) >> 16;
    data[4] = (0x0000ff00 & step) >> 8;
    data[5] = (0x000000ff & step);
    data[6] = (0x00ff0000 & (speed * 100)) >> 16;
    data[7] = (0x0000ff00 & (speed * 100)) >> 8;
    data[8] = (0x000000ff & (speed * 100));
    data[9] = (0x00ff0000 & speed) >> 16;
    data[10] = (0x0000ff00 & speed) >> 8;
    data[11] = (0x000000ff & speed);
    data[12] = (0x00ff0000 & (speed * 100)) >> 16;
    data[13] = (0x0000ff00 & (speed * 100)) >> 8;
    data[14] = (0x000000ff & (speed * 100));

    g_comm_mutex.lock();
    int r = sendcmd(CMD_MOVEVEL, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 15 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
#ifdef SHOW_DEBUGMSG
    debug_reply("mcMoveVel", reply, len);
#endif
    return (reply[ACKC] == (CMD_MOVEVEL + 0x10));
}

bool mcMoveVel(uint8_t id, uint8_t dir, unsigned int step, int speedmax, int speedacc, int speeddec)
{
    uint8_t data[15];
    data[0] = id;
    data[1] = dir;
    data[2] = (0xff000000 & step) >> 24;
    data[3] = (0x00ff0000 & step) >> 16;
    data[4] = (0x0000ff00 & step) >> 8;
    data[5] = (0x000000ff & step);
    data[6] = (0x00ff0000 & speedacc) >> 16;
    data[7] = (0x0000ff00 & speedacc) >> 8;
    data[8] = (0x000000ff & speedacc);
    data[9] = (0x00ff0000 & speedmax) >> 16;
    data[10] = (0x0000ff00 & speedmax) >> 8;
    data[11] = (0x000000ff & speedmax);
    data[12] = (0x00ff0000 & speeddec) >> 16;
    data[13] = (0x0000ff00 & speeddec) >> 8;
    data[14] = (0x000000ff & speeddec);

    g_comm_mutex.lock();
    int r = sendcmd(CMD_MOVEVEL, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 15 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
#ifdef SHOW_DEBUGMSG
    debug_reply("mcMoveVel", reply, len);
#endif
    return (reply[ACKC] == (CMD_MOVEVEL + 0x10));
}

bool mcMoveAbs(uint8_t id, uint8_t dir, unsigned int step, int speedmax, int speedacc, int speeddec)
{
    uint8_t data[15];
    data[0] = id;
    data[1] = dir;
    data[2] = (0xff000000 & step) >> 24;
    data[3] = (0x00ff0000 & step) >> 16;
    data[4] = (0x0000ff00 & step) >> 8;
    data[5] = (0x000000ff & step);
    data[6] = (0x00ff0000 & speedacc) >> 16;
    data[7] = (0x0000ff00 & speedacc) >> 8;
    data[8] = (0x000000ff & speedacc);
    data[9] = (0x00ff0000 & speedmax) >> 16;
    data[10] = (0x0000ff00 & speedmax) >> 8;
    data[11] = (0x000000ff & speedmax);
    data[12] = (0x00ff0000 & speeddec) >> 16;
    data[13] = (0x0000ff00 & speeddec) >> 8;
    data[14] = (0x000000ff & speeddec);

    g_comm_mutex.lock();
    int r = sendcmd(CMD_MOVEABS, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 15 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
#ifdef SHOW_DEBUGMSG
    debug_reply("mcMoveAbs", reply, len);
#endif
    return (reply[ACKC] == (CMD_MOVEABS + 0x10));
}

bool mcInit(uint8_t id, uint8_t dir, int speed)
{
    uint8_t data[5];
    data[0] = id;
    data[1] = dir;
    data[2] = (0x00ff0000 & speed) >> 16;
    data[3] = (0x0000ff00 & speed) >> 8;
    data[4] = (0x000000ff & speed);

    g_comm_mutex.lock();
    int r = sendcmd(CMD_INIT, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 5 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
#ifdef SHOW_DEBUGMSG
    debug_reply("mcInit", reply, len);
#endif
    return (reply[ACKC] == (CMD_INIT + 0x10));
}

bool mcStop(uint8_t id)
{
    uint8_t data[1] = { id };

    g_comm_mutex.lock();
    int r = sendcmd(CMD_STOP, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 1 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
#ifdef SHOW_DEBUGMSG
    debug_reply("mcStop", reply, len);
#endif
    return (reply[ACKC] == (CMD_STOP + 0x10));
}

bool mcStopDecl(uint8_t id, uint8_t dec)
{
    uint8_t data[2] = { id, dec };

    g_comm_mutex.lock();
    int r = sendcmd(CMD_STOPDECL, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 2 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    if (reply[ACKC] != (CMD_STOPDECL + 0x10)) return false;
    if (reply[ACKD + 1] != 0x00) return false;
    return true;
}

bool mcGetError(uint8_t id, int& ret)
{
    uint8_t data[1] = { id };

    g_comm_mutex.lock();
    int r = sendcmd(CMD_GETERROR, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 2 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    if (reply[ACKC] != (CMD_GETERROR + 0x10)) return false;
    ret = reply[ACKD + 1];
    return true;
}

bool mcGetState(uint8_t id, int& ret)
{
    uint8_t data[1] = { id };

    g_comm_mutex.lock();
    int r = sendcmd(CMD_GETSTATE, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 2 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    if (reply[ACKC] != (CMD_GETSTATE + 0x10)) return false;
    ret = reply[ACKD + 1];
    return true;
}

bool mcGetConnectionState(uint8_t id, int& ret)
{
    uint8_t data[1] = { id };

    g_comm_mutex.lock();
    int r = sendcmd(CMD_GETCONSTATE, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 2 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    if (reply[ACKC] != (CMD_GETCONSTATE + 0x10)) return false;
    ret = reply[ACKD + 1];
    return true;
}

bool mcSetTorqueLimit(uint8_t id, uint8_t torque)
{
    uint8_t data[2] = { id, torque };

    g_comm_mutex.lock();
    int r = sendcmd(CMD_SETTORQUE, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 2 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    return (reply[ACKC] == (CMD_SETTORQUE + 0x10));
}

bool mcSetStallGuard(uint8_t id, uint8_t thr)
{
    uint8_t data[2] = { id, thr };

    g_comm_mutex.lock();
    int r = sendcmd(CMD_SETSTALLGUARD, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 2 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    return (reply[ACKC] == (CMD_SETSTALLGUARD + 0x10));
}

bool mcGetSensorState(bool states[5])
{
    g_comm_mutex.lock();
    int r = sendcmd(CMD_GETSENSORSTATE, NULL, 0);
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 5 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    if (reply[ACKC] != (CMD_GETSENSORSTATE + 0x10)) return false;

    states[0] = !(bool)reply[ACKD + 0];  // Bending sensor (inverted)
    states[1] = (bool)reply[ACKD + 1];   // Feeding sensor #1
    states[2] = (bool)reply[ACKD + 2];   // Feeding sensor #2
    states[3] = !(bool)reply[ACKD + 3];  // Retraction sensor (inverted)
    states[4] = !(bool)reply[ACKD + 4];  // Cutting sensor (inverted)
    return true;
}

int mcGetRes(uint8_t id)
{
    int r = g_motorres[id - 1];
    assert(r);
    return r;
}

bool mcSetRes(uint8_t id, uint8_t res)
{
    uint8_t data[2] = { id, res };
    g_motorres[id - 1] = (256 >> res);

    g_comm_mutex.lock();
    int r = sendcmd(CMD_SETRESOLUTION, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 2 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    return (reply[ACKC] == (CMD_SETRESOLUTION + 0x10));
}

bool mcGetPos(uint8_t id, int& ret)
{
    uint8_t data[1] = { id };

    g_comm_mutex.lock();
    int r = sendcmd(CMD_GETPOSITION, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 6 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    if (reply[ACKC] != (CMD_GETPOSITION + 0x10)) return false;

    int sign = reply[ACKD + 1];
    ret = reply[ACKD + 2] << 24 | reply[ACKD + 3] << 16 | reply[ACKD + 4] << 8 | reply[ACKD + 5];
    if (1 == sign)
        ret = -ret;
    return true;
}

bool mcSetLight(uint8_t id, uint8_t r, uint8_t g, uint8_t b, float dim)
{
    uint8_t data[4];
    data[0] = id;
    data[1] = (uint8_t)((float)r * dim);
    data[2] = (uint8_t)((float)g * dim);
    data[3] = (uint8_t)((float)b * dim);

    g_comm_mutex.lock();
    int ret = sendcmd(CMD_SETBRIGHTNESS, data, sizeof(data));
    if (E_CLOSED == ret) { g_comm_mutex.unlock(); return false; }

    const int ps = 4 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    return (reply[ACKC] == (CMD_SETBRIGHTNESS + 0x10));
}

bool mcSayHello()
{
    g_comm_mutex.lock();
    int r = sendcmd(CMD_HELLO, NULL, 0);
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    return (reply[ACKC] == (CMD_HELLO + 0x10));
}

bool mcGetVersion(char v[6])
{
    g_comm_mutex.lock();
    int r = sendcmd(CMD_GETVERSION, NULL, 0);
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 5 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    if (reply[ACKC] != (CMD_GETVERSION + 0x10)) return false;

    memcpy(v, &reply[ACKD + 0], 5);
    v[5] = 0;
    return true;
}

bool mcWriteData(unsigned int addr, uint8_t size, uint8_t* p)
{
    uint8_t data[103];
    data[0] = (0x0000ff00 & addr) >> 8;
    data[1] = (0x000000ff & addr);
    if (size > 100) size = 100;
    data[2] = size;
    memcpy(&data[3], p, size);

    g_comm_mutex.lock();
    int r = sendcmd(CMD_WRITE, data, 3 + size);
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 1 + 5;
    uint8_t reply[ps];
    int len = getack(reply, ps, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    if (reply[ACKC] != (CMD_WRITE + 0x10)) return false;
    if (reply[ACKD] != 0x00) return false;
    return true;
}

bool mcReadData(unsigned int addr, uint8_t size, uint8_t* p)
{
    uint8_t data[3];
    data[0] = (0x0000ff00 & addr) >> 8;
    data[1] = (0x000000ff & addr);
    if (size > 100) size = 100;
    data[2] = size;

    g_comm_mutex.lock();
    int r = sendcmd(CMD_READ, data, sizeof(data));
    if (E_CLOSED == r) { g_comm_mutex.unlock(); return false; }

    const int ps = 103 + 5;
    uint8_t reply[ps];
    int len = getack(reply, size + 3 + 5, __FUNCTION__);
    g_comm_mutex.unlock();
    if (E_CLOSED == len) return false;
    if (0 > len) return false;
    if (reply[ACKC] != (CMD_READ + 0x10)) return false;

    size = reply[ACKD + 2];
    memcpy(p, &reply[ACKD + 3], size);
    return true;
}


//-------------------------------------- MOTOR LOGIC -----------------------------------------------

int mlWriteData(uint8_t* p, int size)
{
    if (size > 0xBFF) return 0;
    int blkunit = 100;
    int nblks = size / blkunit;
    int pidx = 0;
    for (int k = 0; k < nblks; k++)
    {
        if (!mcWriteData(pidx, blkunit, &p[pidx]))
        {
            printf("* Write error at %d\n", pidx);
            return 0;
        }
        pidx += blkunit;
    }
    int rest = size % blkunit;
    if (rest > 0)
    {
        if (!mcWriteData(pidx, rest, &p[pidx]))
        {
            printf("* Write error at %d\n", pidx);
            return 0;
        }
    }
    return size;
}

int mlReadData(uint8_t* p, int size)
{
    if (size > 0xBFF) return 0;
    int blkunit = 16;
    int nblks = size / blkunit;
    int pidx = 0;
    for (int k = 0; k < nblks; k++)
    {
        if (!mcReadData(pidx, blkunit, &p[pidx])) return 0;
        pidx += blkunit;
    }
    int rest = size % blkunit;
    if (rest > 0)
    {
        if (!mcReadData(pidx, rest, &p[pidx])) return 0;
    }
    return size;
}

int mlCheckMotorStop(uint8_t id)
{
    int ret = 0;
    if (mcGetError(id, ret))
    {
        if ((ret & 0x80) == 0x80) return S_STOP;
        if (ret & 0x01)
        {
            mcStop(id);
            return S_STALL;
        }
    }
    return 0;
}

int mlWaitMotor(uint8_t id, double timeout)
{
    LARGE_INTEGER tstart, tend;
    QueryPerformanceCounter(&tstart);

    while (1)
    {
        int ret = 0;
        if (mcGetError(id, ret))
        {
            if ((ret & 0x80) == 0x80) return S_STOP;
            if (ret & 0x01)
            {
                mcStop(id);
                return S_STALL;
            }
        }
        else
        {
            return E_CMD;
        }

        QueryPerformanceCounter(&tend);
        double sec = PerfElapsedSec(tstart, tend);
        if (sec >= timeout)
            return E_TIMEOUT;
    }
    return 0;
}

int mlWaitMotor2(uint8_t id, double timeout)
{
    LARGE_INTEGER tstart, tend;
    QueryPerformanceCounter(&tstart);

    while (1)
    {
        int ret = 0;
        if (mcGetState(id, ret))
        {
            if (ret == 0x00) return S_STOP;
        }
        else
        {
            return E_CMD;
        }

        QueryPerformanceCounter(&tend);
        double sec = PerfElapsedSec(tstart, tend);
        if (sec >= timeout)
            return E_TIMEOUT;
    }
    return 0;
}

void mlCutterUp(bool bUp)
{
    const int mid = MID_CUTTER;
    mcStop(mid);
    mcSetTorqueLimit(mid, 0x1F);
    if (bUp)
        mcMoveAbs(mid, DIR_CW, DEG2STEP(0, mid), 500);
    else
        mcMoveAbs(mid, DIR_CW, DEG2STEP(180, mid), 500);
    if (E_TIMEOUT == mlWaitMotor(mid, 5.0)) printf("[ERROR] mlWaitMotor (MID_CUTTER)\n");
    mcSetTorqueLimit(mid, 8);
}

void mlPinUp(bool bUp)
{
    const int mid = MID_LIFTER;
    if (bUp)
        mcMoveAbs(mid, DIR_CW, DEG2STEP(0, mid), 1000);
    else
        mcMoveAbs(mid, DIR_CW, DEG2STEP(180, mid), 1000);
    if (E_TIMEOUT == mlWaitMotor(mid, 5.0)) printf("[ERROR] mlWaitMotor (MID_LIFTER)\n");
}

void mlPinHeight(float r)
{
    const int mid = MID_LIFTER;
    mcMoveAbs(mid, DIR_CW, DEG2STEP(180 * (1.0 - r), mid), 1000);
    if (E_TIMEOUT == mlWaitMotor(mid, 5.0)) printf("[ERROR] mlWaitMotor (MID_LIFTER)\n");
}

void mlBendingReset(bool bDir, float margin, float base, int speed)
{
    const int mid = MID_BENDER;
    if (bDir)
        mlBending(base, margin, base, speed);
    else
        mlBending(-base, margin, base, speed);
    mlWaitMotor2(mid);
}

void mlBending(float angle, float margin, float base, int speed)
{
    const int mid = MID_BENDER;
    if (angle < 0.0f)
        mcMoveAbs(mid, DIR_CCW, DEG2STEP(-(margin + angle + base), mid), speed);
    else
        mcMoveAbs(mid, DIR_CW, DEG2STEP((margin + angle + base), mid), speed);
    mlWaitMotor2(mid);
}

void mlVisionLight(uint8_t b)    { mcSetLight(1, b, b, b); }

void mlLogoLight(int msg, uint8_t r, uint8_t g, uint8_t b, float dim)
{
    mcSetLight(msg, r, g, b, dim);
}

void mlLogoLight(int msg, float dim)
{
    switch (msg) {
    case 0: mcSetLight(0, 0, 0, 0, 0); break;
    case 1: mcSetLight(0, 255, 255, 255, dim); break;
    case 2: mcSetLight(0, 255, 0, 0, dim); break;
    case 3: mcSetLight(0, 0, 255, 0, dim); break;
    case 4: mcSetLight(0, 0, 0, 255, dim); break;
    }
}

void mlLogoLightBlink(int msg, int loop, int delay)
{
    for (int k = 0; k < loop; k++) {
        mlLogoLight(msg, 1.0f); Sleep(delay);
        mlLogoLight(msg, 0.0f); Sleep(delay);
    }
}

void mlLogoLightBlinkSoft(int msg, int loop, int delay)
{
    for (int k = 0; k < loop; k++) {
        for (int q = 0; q < 256; q++)
            if ((q % 20) == 0) { mlLogoLight(msg, (float)q / 255.0f); Sleep(delay); }
        for (int q = 255; q > 0; q--)
            if ((q % 20) == 0) { mlLogoLight(msg, (float)q / 255.0f); Sleep(delay); }
    }
    mlLogoLight(msg, 0.0f);
}

void thread_mlLogoLightHeartbeatAsync(int msg)
{
    mlLogoLight(msg, 1.0f);
    while (g_lightheartbeat_flag.load()) {
        for (int k = 255; k >= 64; k--)
            if ((k % 20) == 0) mlLogoLight(msg, (float)k / 255.0f);
        for (int k = 64; k < 256; k++)
            if ((k % 20) == 0) mlLogoLight(msg, (float)k / 255.0f);
        Sleep(50);
    }
    mlLogoLight(msg, 0.0f);
    g_lightheartbeatthread = NULL;
}

void mlLogoLightHeartbeatStart(int msg)
{
    if (g_lightheartbeatthread) return;
    g_lightheartbeat_flag.store(true);
    g_lightheartbeatthread = new std::thread(thread_mlLogoLightHeartbeatAsync, msg);
}

void mlLogoLightHeartbeatEnd()
{
    g_lightheartbeat_flag.store(false);
}

void mlLogoLightOn(int msg)
{
    for (int q = 0; q < 256; q++)
        if ((q % 10) == 0) { mlLogoLight(msg, (float)q / 255.0f); Sleep(20); }
    mlLogoLight(msg, 1.0f);
}

void mlLogoLightOff(int msg)
{
    for (int q = 255; q > 0; q--)
        if ((q % 10) == 0) { mlLogoLight(msg, (float)q / 255.0f); Sleep(20); }
    mlLogoLight(msg, 0.0f);
}

void mlInit(int id)
{
    switch (id)
    {
    case MID_BENDER:
        mcSetTorqueLimit(id, 0x10);
        mcSetStallGuard(id, 10);
        mcInit(id, DIR_CW, 1000);
        if (S_STALL == mlWaitMotor2(id)) printf("Bending motor stalled.\n");
        break;
    case MID_LIFTER:
        mcSetTorqueLimit(id, 0x10);
        mcSetStallGuard(id, 8);
        mcInit(id, DIR_CW, 1000);
        if (S_STALL == mlWaitMotor2(id)) printf("Retraction motor stalled.\n");
        mlPinHeight(0.0);
        break;
    case MID_CUTTER:
        mcSetTorqueLimit(id, 0x1F);
        mcSetStallGuard(id, 8);
        mcInit(id, DIR_CW, 1000);
        if (S_STALL == mlWaitMotor2(id)) printf("Cutter motor stalled.\n");
        else mlCutterUp(true);
        break;
    case MID_FEEDER:
        mcSetTorqueLimit(id, 0x12);
        mcSetStallGuard(id, 7);
        mcInit(id, DIR_CW, 1000);
        if (S_STALL == mlWaitMotor2(id)) printf("Feeder motor stalled.\n");
        break;
    }
}

bool mlInitIdle(int id)
{
    switch (id)
    {
    case MID_BENDER:
        mcSetTorqueLimit(id, 8); mcSetStallGuard(id, 4);
        mcInit(id, DIR_CW, 1000);
        if (S_STALL == mlWaitMotor(id)) { printf("Bending motor stalled.\n"); return false; }
        break;
    case MID_LIFTER:
        mcSetTorqueLimit(id, 8); mcSetStallGuard(id, 4);
        mcInit(id, DIR_CW, 1000);
        if (S_STALL == mlWaitMotor(id)) { printf("Retraction motor stalled.\n"); return false; }
        break;
    case MID_CUTTER:
        mcSetTorqueLimit(id, 10); mcSetStallGuard(id, 8);
        mcInit(id, DIR_CW, 1000);
        if (S_STALL == mlWaitMotor(id)) { printf("Cutter motor stalled.\n"); return false; }
        break;
    }
    return true;
}

bool mlInMotion(int id)
{
    int ret = 0;
    if (mcGetState(id, ret))
        return ret != 0;
    return false;
}


//----------------------------------------------- Communications ------------------------------------------------
void mcCloseComm()
{
    if (g_comm)
    {
        g_comm->close();
        delete g_comm;
        g_comm = NULL;
    }
}

bool IsCommConnected()
{
    return (g_comm != NULL);
}

// Linux port: takes string port path instead of int port number
bool mcConnectComm(const std::string& port, int baudrate, int timeout)
{
    mcCloseComm();
    try
    {
        g_comm = new serial::Serial(port, baudrate, serial::Timeout::simpleTimeout(timeout));
    }
    catch (serial::IOException& e)
    {
        printf("%s\n", e.what());
        mcCloseComm();
        return false;
    }

    if (mcSayHello())
        return true;

    mcCloseComm();
    return false;
}

bool mcFindComm(int baudrate)
{
    std::vector<serial::PortInfo> devices_found = serial::list_ports();

    for (auto& device : devices_found)
    {
        printf("  Trying %s (%s)...\n", device.port.c_str(), device.description.c_str());

        if (mcConnectComm(device.port, baudrate, 1000))
        {
            printf("* Bender 2 found on %s\n", device.port.c_str());
            return true;
        }
    }

    return false;
}
