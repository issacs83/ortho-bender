/*
 * stub.h - Motor control API header (Linux port)
 * Original: YOAT Corporation B2 TEST PROGRAM
 * Ported for i.MX8MP-EVK hardware verification
 */
#pragma once

#include <string>
#include <cassert>
#include <cstdint>
#include "platform.h"
#include "serial/serial.h"

#define BAUDRATE            19200

#define MM2DEG(x)           ((double)(x)*3.6)
#define MM2STEP(x)          DEG2STEP(MM2DEG(x),MID_FEEDER)
#define DEG2MM(x)           ((double)(x)/3.6)
#define STEP2MM(x)          DEG2MM(STEP2DEG(x, MID_FEEDER))
#define DEG2STEP(x,id)      (unsigned int)((double)(x)/(1.8/(double)(mcGetRes(id))))
#define STEP2DEG(x,id)      ((double)(x)*(1.8/(double)(mcGetRes(id))))

#define E_TIMEOUT           -1000
#define E_CMD               -1001
#define E_PROTOCOL          -1002
#define E_ACK               -1003
#define E_OVERFLOW          -1004
#define E_CLOSED            -1005
#define E_NOTCON            -1006

#define S_STOP              1
#define S_STALL             2

#define ACKC                1
#define ACKD                2

#define MID_BENDER          0x01
#define MID_FEEDER          0x02
#define MID_LIFTER          0x03
#define MID_CUTTER          0x04

#define DIR_CW              0x00
#define DIR_CCW             0x01

#define CMD_INIT            0x50
#define CMD_MOVEVEL         0x53
#define CMD_MOVEABS         0x54
#define CMD_STOP            0x55
#define CMD_STOPDECL        0x56
#define CMD_GETCONSTATE     0xA1
#define CMD_GETSTATE        0xA2
#define CMD_GETERROR        0xA4
#define CMD_SETTORQUE       0x51
#define CMD_SETRESOLUTION   0x52
#define CMD_SETBRIGHTNESS   0x57
#define CMD_GETPOSITION     0xA3
#define CMD_GETSENSORSTATE  0xA5
#define CMD_SETSTALLGUARD   0x58
#define CMD_WRITE           0x59
#define CMD_READ            0xA6
#define CMD_HELLO           0xA7
#define CMD_GETVERSION      0xA9
#define CMD_PROTOCOLERROR   0xB8

// externs
extern LARGE_INTEGER    g_frequency;
extern serial::Serial*  g_comm;

// Motor Control APIs
bool mcMoveVel2(uint8_t id, uint8_t dir, unsigned int step, int speed);
bool mcMoveVel(uint8_t id, uint8_t dir, unsigned int step, int speedmax, int speedacc = 100000, int speeddec = 100000);
bool mcMoveAbs(uint8_t id, uint8_t dir, unsigned int step, int speedmax, int speedacc = 100000, int speeddec = 100000);
bool mcInit(uint8_t id, uint8_t dir, int speed);
bool mcStop(uint8_t id);
bool mcStopDecl(uint8_t id, uint8_t dec);
bool mcGetState(uint8_t id, int& ret);
bool mcGetConnectionState(uint8_t id, int& ret);
bool mcSetTorqueLimit(uint8_t id, uint8_t torque);
bool mcSetRes(uint8_t id, uint8_t res);
int mcGetRes(uint8_t id);
bool mcGetPos(uint8_t id, int& ret);
bool mcSetLight(uint8_t id, uint8_t r, uint8_t g, uint8_t b, float dim = 1.0f);
bool mcSayHello();
bool mcWriteData(unsigned int addr, uint8_t len, uint8_t* p);
bool mcReadData(unsigned int addr, uint8_t len, uint8_t* p);
bool mcSetStallGuard(uint8_t id, uint8_t thr);
bool mcGetSensorState(bool states[5]);
bool mcGetError(uint8_t id, int& ret);
bool mcGetVersion(char v[6]);

// Motor Logic APIs
int mlWriteData(uint8_t* p, int size);
int mlReadData(uint8_t* p, int size);
int mlWaitMotor(uint8_t id, double timeout = 20.0);
int mlWaitMotor2(uint8_t id, double timeout = 5.0);
int mlCheckMotorStop(uint8_t id);
void mlCutterUp(bool bUp);
void mlPinUp(bool bUp);
void mlPinHeight(float r);
void mlBending(float angle, float margin = -12.0f, float base = 60.0f, int speed = 1000);
void mlBendingReset(bool bDir, float margin = -12.0f, float base = 60.0f, int speed = 1000);
void mlInit(int id);
bool mlInitIdle(int id);
bool mlInMotion(int id);

void mlVisionLight(uint8_t b);
void mlLogoLight(int msg, float dim = 1.0f);
void mlLogoLight(int msg, uint8_t r, uint8_t g, uint8_t b, float dim = 1.0f);
void mlLogoLightBlink(int msg, int loop, int delay);
void mlLogoLightBlinkSoft(int msg, int loop, int delay);
void mlLogoLightOn(int msg);
void mlLogoLightOff(int msg);
void mlLogoLightHeartbeatStart(int msg);
void mlLogoLightHeartbeatEnd();

bool mcFindComm(int baudrate = BAUDRATE);
bool mcConnectComm(const std::string& port, int baudrate = BAUDRATE, int timeout = 1000);
void mcCloseComm();
bool IsCommConnected();
