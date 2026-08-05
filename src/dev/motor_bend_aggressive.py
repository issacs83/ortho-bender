#!/usr/bin/env python3
"""BEND aggressive init — CS settle 1ms, 3000 init cycles, status monitor.
   Diagnose if BEND chip CS toggle is the bottleneck."""
import os, time, sys, fcntl, struct
import spidev, gpiod

TARGET_HZ = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
DURATION  = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0

SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40

def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)

CHOPCONF = 0x99548
SMARTEN  = 0xA0000
DRVCONF  = 0xEF050   # RDSEL=01 → SG_VAL readback
DRVCTRL  = 0x00300
SGCSCONF_ON  = sgcs(19)
SGCSCONF_OFF = 0xD3F00
CHOP_OFF = 0x80000
SEQ = [CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF_ON]

LOW = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

# IMPORTANT: open SPI FIRST to reset spi-imx state (otherwise GPIO line 23 EBUSY)
spi = spidev.SpiDev(); spi.open(1, 0)
spi.max_speed_hz = 50_000; spi.bits_per_word = 8
try: spi.mode = 3
except OSError: pass
fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', 3 | SPI_NO_CS))
spi.xfer2([0,0,0]); time.sleep(0.05)  # dummy xfer to settle

gpio3 = gpiod.Chip('/dev/gpiochip2')
gpio5 = gpiod.Chip('/dev/gpiochip4')
req3 = gpio3.request_lines(consumer='bend_aggr3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='bend_aggr5', config={
    13: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})

CS_DELAY = 0.0005  # 500us
INIT_CYCLES = 1000  # was 500

def xfer_bend(v):
    req3.set_value(22, LOW); time.sleep(CS_DELAY)
    rx = spi.xfer2(to_b(v))
    time.sleep(CS_DELAY); req3.set_value(22, HIGH)
    time.sleep(CS_DELAY)
    return (rx[0]<<16) | (rx[1]<<8) | rx[2]

def parse(rxv):
    sg_val = (rxv >> 10) & 0x3FF
    s = rxv & 0xFF
    flags = []
    if (s>>0)&1: flags.append('SG')
    if (s>>1)&1: flags.append('OT')
    if (s>>2)&1: flags.append('OTPW')
    if (s>>3)&1: flags.append('S2GA')
    if (s>>4)&1: flags.append('S2GB')
    if (s>>5)&1: flags.append('OLA')
    if (s>>6)&1: flags.append('OLB')
    fs = ','.join(flags) if flags else 'OK'
    stst = 'STST' if (s>>7)&1 else 'RUN '
    return f"SG={sg_val:4d} {stst} [{fs}]"

print("=== BEND AGGRESSIVE INIT ===")
print(f"CS_DELAY={CS_DELAY*1000:.1f}ms, INIT_CYCLES={INIT_CYCLES}")

# Pre-init status
print("\n[pre-init status]")
rxv = xfer_bend(SGCSCONF_ON)
print(f"  rx=0x{rxv:05X}  {parse(rxv)}")

print(f"\n[init {INIT_CYCLES} cycles with 1ms CS settle]")
t0 = time.time()
# checkpoint every 1000 cycles
for cycle in range(INIT_CYCLES):
    for v in SEQ:
        xfer_bend(v)
    if (cycle+1) % 1000 == 0:
        rxv = xfer_bend(SGCSCONF_ON)
        print(f"  cycle {cycle+1:5d} (t={time.time()-t0:5.1f}s)  rx=0x{rxv:05X}  {parse(rxv)}")

print(f"\n[post-init status x5]")
for i in range(5):
    rxv = xfer_bend(SGCSCONF_ON)
    print(f"  rx=0x{rxv:05X}  {parse(rxv)}")
    time.sleep(0.1)

# PWM
P = '/sys/class/pwm/pwmchip2/pwm0'
if not os.path.isdir(P):
    with open('/sys/class/pwm/pwmchip2/export','w') as f: f.write('0\n')
    time.sleep(0.05)

def set_hz(h):
    period = int(1e9/h); duty = period//2
    with open(f'{P}/duty_cycle','w') as f: f.write('0\n')
    with open(f'{P}/period','w') as f: f.write(f'{period}\n')
    with open(f'{P}/duty_cycle','w') as f: f.write(f'{duty}\n')
    with open(f'{P}/enable','w') as f: f.write('1\n')

with open(f'{P}/enable','w') as f: f.write('0\n')
print(f"\n[ramp 200 -> {TARGET_HZ}]")
for i in range(15):
    h = int(200 + (TARGET_HZ-200)*i/14)
    set_hz(h); time.sleep(1.5/15)

print(f"\n[RUN @ {TARGET_HZ} Hz, monitor every 0.5s]")
t0 = time.time()
while time.time()-t0 < DURATION:
    rxv = xfer_bend(SGCSCONF_ON)
    print(f"  t={time.time()-t0:4.1f}s  rx=0x{rxv:05X}  {parse(rxv)}")
    time.sleep(0.5)

print("\n[ramp down]")
for i in range(10):
    h = int(TARGET_HZ - (TARGET_HZ-200)*i/9)
    set_hz(h); time.sleep(1.0/10)
with open(f'{P}/enable','w') as f: f.write('0\n')

# silence
for _ in range(50):
    xfer_bend(CHOP_OFF); xfer_bend(SGCSCONF_OFF)

req3.release(); req5.release(); spi.close()
print("\n[done]")
