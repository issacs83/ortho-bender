#!/usr/bin/env python3
"""SDOFF=1 mode test: bypass STEP/DIR pin, drive motor via SPI direct microstep command.
   If motor rotates in SDOFF=1, chip driver is OK; STEP input is the problem.
   If motor doesn't rotate, chip driver itself is faulty."""
import sys, time, fcntl, struct
import spidev, gpiod

CHIP = sys.argv[1].upper() if len(sys.argv) > 1 else 'BEND'
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0

SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40

def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)

# DRVCONF with SDOFF=1 (bit 7)
DRVCONF_SDOFF = 0xEF0D0   # SDOFF=1, RDSEL=01, VSENSE=1
CHOPCONF = 0x99548
SMARTEN  = 0xA0000
SGCSCONF = sgcs(27)   # CS=27 (stronger current ~1.5A)
SGCSCONF_OFF = 0xD3F00
CHOP_OFF = 0x80000

# DRVCTRL in SDOFF=1 mode encodes coil currents directly:
# bits[19:18]=00 (DRVCTRL opcode), bit[17]=PHA, bit[16:9]=CA[8:0], bit[8]=PHB, bit[7:0]=CB[7:0]
# We'll cycle through 4-step pattern for motor rotation
def drvctrl_sdoff(pha, ca, phb, cb):
    return ((pha&1)<<17) | ((ca&0x1FF)<<9) | ((phb&1)<<8) | (cb&0xFF)

# 4-step full step pattern: A+, B+, A-, B-
STEPS = [
    drvctrl_sdoff(0, 248, 0, 0),    # +A 0
    drvctrl_sdoff(0, 0, 0, 248),    # +B 0
    drvctrl_sdoff(1, 248, 0, 0),    # -A 0
    drvctrl_sdoff(0, 0, 1, 248),    # -B 0
]

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
req3 = gpio3.request_lines(consumer='sdoff3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='sdoff5', config={
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

def parse(rxv):
    sg = (rxv >> 10) & 0x3FF
    s = rxv & 0xFF
    fl = []
    if (s>>0)&1: fl.append('SG')
    if (s>>1)&1: fl.append('OT')
    if (s>>3)&1: fl.append('S2GA')
    if (s>>4)&1: fl.append('S2GB')
    if (s>>5)&1: fl.append('OLA')
    if (s>>6)&1: fl.append('OLB')
    return f"SG={sg:4d} {'STST' if (s>>7)&1 else 'RUN '} [{','.join(fl) if fl else 'OK'}]"

print(f"=== {CHIP} SDOFF=1 mode test ===")
print(f"[init: CHOPCONF, SMARTEN, DRVCONF(SDOFF=1), SGCSCONF(CS=27)]")

# Init with SDOFF=1
INIT_SEQ = [CHOPCONF, SMARTEN, DRVCONF_SDOFF, SGCSCONF]
for _ in range(500):
    for v in INIT_SEQ: xfer(v)

print(f"[post-init]")
rxv = xfer(SGCSCONF); print(f"  {parse(rxv)}")

# Direct motor rotation via SPI: cycle through 4-step pattern
print(f"\n[SPI-driven rotation @ ~50Hz step rate, {DURATION}s]")
step_period = 0.02  # 50Hz step
t0 = time.time()
i = 0
while time.time() - t0 < DURATION:
    xfer(STEPS[i % 4])
    i += 1
    if i % 50 == 0:  # every 1s ~
        rxv = xfer(SGCSCONF)
        print(f"  step {i:4d}  {parse(rxv)}")
    time.sleep(step_period)

# silence
for _ in range(50): xfer(CHOP_OFF); xfer(SGCSCONF_OFF)
req3.release(); req5.release(); spi.close()
print(f"[done] total {i} steps sent")
