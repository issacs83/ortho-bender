"""
Protocol constants ported from stub.h.
"""

# Frame delimiters
STX = 0x5B
ETX = 0x5D

# ACK offsets in reply frame
ACKC = 1  # Command byte position
ACKD = 2  # Data start position

# Motor IDs
MID_BENDER = 0x01
MID_FEEDER = 0x02
MID_LIFTER = 0x03
MID_CUTTER = 0x04

MOTOR_NAMES = {
    MID_BENDER: "bender",
    MID_FEEDER: "feeder",
    MID_LIFTER: "lifter",
    MID_CUTTER: "cutter",
}
MOTOR_IDS = {v: k for k, v in MOTOR_NAMES.items()}

# Directions
DIR_CW = 0x00
DIR_CCW = 0x01

# Commands
CMD_INIT = 0x50
CMD_SETTORQUE = 0x51
CMD_SETRESOLUTION = 0x52
CMD_MOVEVEL = 0x53
CMD_MOVEABS = 0x54
CMD_STOP = 0x55
CMD_STOPDECL = 0x56
CMD_SETBRIGHTNESS = 0x57
CMD_SETSTALLGUARD = 0x58
CMD_WRITE = 0x59
CMD_GETCONSTATE = 0xA1
CMD_GETSTATE = 0xA2
CMD_GETPOSITION = 0xA3
CMD_GETERROR = 0xA4
CMD_GETSENSORSTATE = 0xA5
CMD_READ = 0xA6
CMD_HELLO = 0xA7
CMD_GETVERSION = 0xA9
CMD_PROTOCOLERROR = 0xB8

# Error codes
E_TIMEOUT = -1000
E_CMD = -1001
E_PROTOCOL = -1002
E_ACK = -1003
E_OVERFLOW = -1004
E_CLOSED = -1005
E_NOTCON = -1006

# Motor stop states
S_STOP = 1
S_STALL = 2

# Serial
BAUDRATE = 19200
