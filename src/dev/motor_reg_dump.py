#!/usr/bin/env python3
"""Per-chip register dump: init then read DRV_STATUS in 3 RDSEL modes.
   Standstill state, no PWM, no rotation."""
import sys, time, fcntl, struct
import spidev, gpiod

CHIP = sys.argv[1].upper() if len(sys.argv) > 1 else 'BEND'
SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40

def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)

CHOPCONF = 0x99548
SMARTEN  = 0xA0000
DRVCTRL  = 0x00300
SGCSCONF_ON = sgcs(19)
# DRVCONF templates with different RDSEL
DRVCONF_RD0 = 0xEF040  # RDSEL=00 MSTEP
DRVCONF_RD1 = 0xEF050  # RDSEL=01 SG_VAL
DRVCONF_RD2 = 0xEF060  # RDSEL=10 SG+CS
SGCSCONF_OFF = 0xD3F00
CHOP_OFF = 0x80000

LOW = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

# SPI first
spi = spidev.SpiDev(); spi.open(1, 0)
spi.max_speed_hz = 50_000; spi.bits_per_word = 8
try: spi.mode = 3
except OSError: pass
fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', 3 | SPI_NO_CS))
spi.xfer2([0,0,0]); time.sleep(0.05)

gpio3 = gpiod.Chip('/dev/gpiochip2')
gpio5 = gpiod.Chip('/dev/gpiochip4')
req3 = gpio3.request_lines(consumer='dump3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='dump5', config={
    13: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})

CS_MAP = {'FEED': (req5, 13), 'BEND': (req3, 22), 'LIFT': (req5, 7)}
cs_req, cs_line = CS_MAP[CHIP]
CS_DELAY = 0.0005

def xfer(v):
    cs_req.set_value(cs_line, LOW); time.sleep(CS_DELAY)
    rx = spi.xfer2(to_b(v))
    time.sleep(CS_DELAY); cs_req.set_value(cs_line, HIGH)
    time.sleep(CS_DELAY)
    return (rx[0]<<16) | (rx[1]<<8) | rx[2]

def status_bits(rxv):
    s = rxv & 0xFF
    return {
        'STST': (s>>7)&1,  'OLB': (s>>6)&1,  'OLA': (s>>5)&1,
        'S2GB': (s>>4)&1,  'S2GA': (s>>3)&1, 'OTPW': (s>>2)&1,
        'OT':   (s>>1)&1,  'SG':  (s>>0)&1,
    }

print(f"=== {CHIP} (CS gpio{'5' if cs_req is req5 else '3'}_{cs_line}) ===")

# Initial readback (no init yet)
print("\n[0] no-init readback (chip default state)")
for i in range(3):
    rxv = xfer(0)
    print(f"  rx=0x{rxv:05X}  status={status_bits(rxv)}")

# Init with RDSEL=0
print("\n[1] init 500x with DRVCONF RDSEL=00 (MSTEP)")
SEQ0 = [CHOPCONF, SMARTEN, DRVCONF_RD0, DRVCTRL, SGCSCONF_ON]
for _ in range(500):
    for v in SEQ0: xfer(v)
for i in range(5):
    rxv = xfer(SGCSCONF_ON)
    msb = (rxv >> 10) & 0x3FF
    print(f"  rx=0x{rxv:05X}  MSTEP={msb:4d}  status={status_bits(rxv)}")

# Switch to RDSEL=01
print("\n[2] switch to RDSEL=01 (SG_VAL) — write DRVCONF then readback")
xfer(DRVCONF_RD1)
for _ in range(20): xfer(SGCSCONF_ON)
for i in range(5):
    rxv = xfer(SGCSCONF_ON)
    sgval = (rxv >> 10) & 0x3FF
    print(f"  rx=0x{rxv:05X}  SG_VAL={sgval:4d}  status={status_bits(rxv)}")

# Switch to RDSEL=10
print("\n[3] switch to RDSEL=10 (SG+CS) — write DRVCONF then readback")
xfer(DRVCONF_RD2)
for _ in range(20): xfer(SGCSCONF_ON)
for i in range(5):
    rxv = xfer(SGCSCONF_ON)
    sg5 = (rxv >> 15) & 0x1F
    cs5 = (rxv >> 10) & 0x1F
    print(f"  rx=0x{rxv:05X}  SG[4:0]={sg5}  CS[4:0]={cs5}  status={status_bits(rxv)}")

# Test write integrity: write CHOPCONF then SGCSCONF and observe status changes
print("\n[4] write test: CHOPCONF=OFF (chopper disable) — STST should reflect")
xfer(DRVCONF_RD1)  # back to SG_VAL
for _ in range(10): xfer(SGCSCONF_ON)
xfer(CHOP_OFF)
for _ in range(10): xfer(0)
for i in range(3):
    rxv = xfer(0)
    print(f"  after CHOP_OFF: rx=0x{rxv:05X}  status={status_bits(rxv)}")
# Now re-enable
xfer(CHOPCONF)
for _ in range(20): xfer(SGCSCONF_ON)
for i in range(3):
    rxv = xfer(SGCSCONF_ON)
    print(f"  after CHOP re-enable: rx=0x{rxv:05X}  status={status_bits(rxv)}")

# silence
for _ in range(50): xfer(CHOP_OFF); xfer(SGCSCONF_OFF)
req3.release(); req5.release(); spi.close()
print("\n[done]")
