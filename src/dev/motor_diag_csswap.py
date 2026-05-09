#!/usr/bin/env python3
"""CS swap variant of motor_diag.py:
  - LIFT mapped to gpio5_13 (was FEED)
  - FEED mapped to gpio5_07 (was LIFT)

Compare readback patterns vs original mapping to determine
true LIFT/FEED chip-to-line wiring.
"""
import os, time, sys, fcntl, struct
import spidev, gpiod

CHIP_NAME = sys.argv[1].upper() if len(sys.argv) > 1 else 'FEED'
TARGET_HZ = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
DURATION  = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0

SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40

def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)
SEQ = [0x99548, 0xA0000, 0xEF050, 0x00300, sgcs(19)]

LOW = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

gpio3 = gpiod.Chip('/dev/gpiochip2')
gpio5 = gpiod.Chip('/dev/gpiochip4')
req3 = gpio3.request_lines(consumer='diag3s', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='diag5s', config={
    13: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})

spi = spidev.SpiDev(); spi.open(1, 0)
spi.max_speed_hz = 50_000; spi.bits_per_word = 8
try: spi.mode = 3
except OSError: pass
fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', 3 | SPI_NO_CS))

# *** SWAPPED MAPPING ***
CS_MAP = {
    'FEED': (req5, 7),    # was 13 → now 7
    'BEND': (req3, 22),   # unchanged
    'LIFT': (req5, 13),   # was 7  → now 13
}
if CHIP_NAME not in CS_MAP:
    print(f'unknown chip {CHIP_NAME}'); sys.exit(1)
cs_req, cs_line = CS_MAP[CHIP_NAME]

def xfer(v):
    cs_req.set_value(cs_line, LOW); time.sleep(0.0001)
    rx = spi.xfer2(to_b(v))
    time.sleep(0.0001); cs_req.set_value(cs_line, HIGH)
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
    flag_s = ','.join(flags) if flags else 'OK'
    stst_s = 'STST' if (s>>7)&1 else 'RUN '
    return f"SG_VAL={sg_val:4d} {stst_s} [{flag_s}]"

print(f"=== {CHIP_NAME} CS-SWAP diag (CS line gpio{'5' if cs_req is req5 else '3'}_{cs_line}) ===")

print("[init] 500x SEQ writes")
for _ in range(500):
    for v in SEQ: xfer(v)

print("\n[STANDSTILL — pre-PWM]")
for i in range(3):
    rxv = xfer(sgcs(19))
    print(f"  rx=0x{rxv:05X}  {parse(rxv)}")
    time.sleep(0.1)

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
print(f"\n[ramp] 200 -> {TARGET_HZ} Hz over 1.5s")
for i in range(15):
    h = int(200 + (TARGET_HZ-200)*i/14)
    set_hz(h); time.sleep(1.5/15)

print(f"\n[RUN @ {TARGET_HZ} Hz]")
t0 = time.time()
while time.time()-t0 < DURATION:
    rxv = xfer(sgcs(19))
    print(f"  t={time.time()-t0:4.1f}s  rx=0x{rxv:05X}  {parse(rxv)}")
    time.sleep(0.4)

print("\n[ramp down]")
for i in range(10):
    h = int(TARGET_HZ - (TARGET_HZ-200)*i/9)
    set_hz(h); time.sleep(1.0/10)
with open(f'{P}/enable','w') as f: f.write('0\n')

# silence
for _ in range(50): xfer(0x80000); xfer(0xD3F00)

req3.release(); req5.release(); spi.close()
print(f"[done] {CHIP_NAME}")
