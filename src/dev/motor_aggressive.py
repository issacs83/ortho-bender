#!/usr/bin/env python3
"""Aggressive init + run for any chip (FEED|BEND|LIFT).
   Key fixes: SPI-first init, 500us CS settle, dummy SPI xfer at startup."""
import os, time, sys, fcntl, struct
import spidev, gpiod

CHIP = sys.argv[1].upper() if len(sys.argv) > 1 else 'BEND'
TARGET_HZ = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
DURATION  = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0

SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40

def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)

CHOPCONF = 0x99548
SMARTEN  = 0xA0000
DRVCONF  = 0xEF050
DRVCTRL  = 0x00300
SGCSCONF_ON  = sgcs(19)
SGCSCONF_OFF = 0xD3F00
CHOP_OFF = 0x80000
SEQ = [CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF_ON]

LOW = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

# SPI first - resets spi-imx state
spi = spidev.SpiDev(); spi.open(1, 0)
spi.max_speed_hz = 50_000; spi.bits_per_word = 8
try: spi.mode = 3
except OSError: pass
fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', 3 | SPI_NO_CS))
spi.xfer2([0,0,0]); time.sleep(0.05)

gpio3 = gpiod.Chip('/dev/gpiochip2')
gpio5 = gpiod.Chip('/dev/gpiochip4')
req3 = gpio3.request_lines(consumer='aggr3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='aggr5', config={
    13: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})

CS_MAP = {'FEED': (req5, 13), 'BEND': (req3, 22), 'LIFT': (req5, 7)}
if CHIP not in CS_MAP:
    print(f'unknown {CHIP}'); sys.exit(1)
cs_req, cs_line = CS_MAP[CHIP]

CS_DELAY = 0.0005  # 500us
INIT_CYCLES = 1000

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
    if (s>>2)&1: fl.append('OTPW')
    if (s>>3)&1: fl.append('S2GA')
    if (s>>4)&1: fl.append('S2GB')
    if (s>>5)&1: fl.append('OLA')
    if (s>>6)&1: fl.append('OLB')
    return f"SG={sg:4d} {'STST' if (s>>7)&1 else 'RUN '} [{','.join(fl) if fl else 'OK'}]"

print(f"=== {CHIP} aggressive (CS_DELAY={CS_DELAY*1000:.1f}ms, INIT={INIT_CYCLES}) ===")
print(f"[pre]   {parse(xfer(SGCSCONF_ON))}")

for cycle in range(INIT_CYCLES):
    for v in SEQ: xfer(v)

print(f"[post]  {parse(xfer(SGCSCONF_ON))}")

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
print(f"[ramp 200 -> {TARGET_HZ}]")
for i in range(15):
    set_hz(int(200 + (TARGET_HZ-200)*i/14)); time.sleep(1.5/15)

print(f"[RUN {TARGET_HZ}Hz {DURATION}s]")
t0 = time.time()
while time.time()-t0 < DURATION:
    rxv = xfer(SGCSCONF_ON)
    print(f"  t={time.time()-t0:4.1f}s  {parse(rxv)}")
    time.sleep(0.5)

for i in range(10):
    set_hz(int(TARGET_HZ - (TARGET_HZ-200)*i/9)); time.sleep(1.0/10)
with open(f'{P}/enable','w') as f: f.write('0\n')

for _ in range(50): xfer(CHOP_OFF); xfer(SGCSCONF_OFF)
req3.release(); req5.release(); spi.close()
print("[done]")
