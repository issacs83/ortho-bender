#!/usr/bin/env python3
"""TMC260C-PA diagnostic — print SG_VALUE + DRV_STATUS during init/ramp/run/stop.

Usage: motor_diag.py FEED|BEND|LIFT [hz=4000] [duration=4.0]

Distinguishes:
  - mechanical stall (SG_VAL drops, STST=0, no fault flags)
  - open load (OLA/OLB flag)
  - short to GND (S2GA/S2GB flag)
  - overtemp (OT/OTPW flag)
  - motor not moving (STST stays 1 during PWM)
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
# DRVCONF: 0xEF050 = SLP=11/11, VSENSE=1, RDSEL=01 → SG_VALUE [19:10] readback (10-bit)
SEQ = [0x99548, 0xA0000, 0xEF050, 0x00300, sgcs(19)]
CHOP_OFF = 0x80000
SGCS_OFF = 0xD3F00

LOW = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

gpio3 = gpiod.Chip('/dev/gpiochip2')
gpio5 = gpiod.Chip('/dev/gpiochip4')
req3 = gpio3.request_lines(consumer='diag3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='diag5', config={
    13: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})

spi = spidev.SpiDev(); spi.open(1, 0)
spi.max_speed_hz = 50_000; spi.bits_per_word = 8
try: spi.mode = 3
except OSError: pass
fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', 3 | SPI_NO_CS))

CS_MAP = {'FEED': (req5, 13), 'BEND': (req3, 22), 'LIFT': (req5, 7)}
if CHIP_NAME not in CS_MAP:
    print(f'unknown chip {CHIP_NAME}'); sys.exit(1)
cs_req, cs_line = CS_MAP[CHIP_NAME]

def xfer(v):
    cs_req.set_value(cs_line, LOW); time.sleep(0.0001)
    rx = spi.xfer2(to_b(v))
    time.sleep(0.0001); cs_req.set_value(cs_line, HIGH)
    return (rx[0]<<16) | (rx[1]<<8) | rx[2]

def parse(rxv):
    # RDSEL=01: bits [19:10] = SG_VALUE (10-bit, 0=stall, 1023=no load)
    sg_val = (rxv >> 10) & 0x3FF
    # Status bits [7:0]
    s = rxv & 0xFF
    stst  = (s >> 7) & 1
    olb   = (s >> 6) & 1
    ola   = (s >> 5) & 1
    s2gb  = (s >> 4) & 1
    s2ga  = (s >> 3) & 1
    otpw  = (s >> 2) & 1
    ot    = (s >> 1) & 1
    sg    = (s >> 0) & 1
    flags = []
    if ot:   flags.append('OT')
    if otpw: flags.append('OTPW')
    if s2ga: flags.append('S2GA')
    if s2gb: flags.append('S2GB')
    if ola:  flags.append('OLA')
    if olb:  flags.append('OLB')
    if sg:   flags.append('STALL')
    flag_s = ','.join(flags) if flags else 'OK'
    stst_s = 'STST' if stst else 'RUN '
    return f"SG_VAL={sg_val:4d}  {stst_s}  flags=[{flag_s}]"

print(f"=== {CHIP_NAME} diag (CS gpio{'5' if cs_req is req5 else '3'}_{cs_line}, target {TARGET_HZ} Hz, {DURATION}s) ===")

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
    set_hz(h)
    time.sleep(1.5/15)

print(f"\n[RUN @ {TARGET_HZ} Hz — sampling every 0.4s]")
t0 = time.time()
samples = []
while time.time()-t0 < DURATION:
    rxv = xfer(sgcs(19))
    print(f"  t={time.time()-t0:4.1f}s  rx=0x{rxv:05X}  {parse(rxv)}")
    samples.append(rxv)
    time.sleep(0.4)

print("\n[ramp down]")
for i in range(10):
    h = int(TARGET_HZ - (TARGET_HZ-200)*i/9)
    set_hz(h); time.sleep(1.0/10)
with open(f'{P}/enable','w') as f: f.write('0\n')

print("\n[POST-STOP]")
for i in range(2):
    rxv = xfer(sgcs(19))
    print(f"  rx=0x{rxv:05X}  {parse(rxv)}")
    time.sleep(0.1)

# summary stats
sg_vals = [(s >> 10) & 0x3FF for s in samples]
if sg_vals:
    print(f"\n[SUMMARY] SG_VAL min={min(sg_vals)} max={max(sg_vals)} avg={sum(sg_vals)//len(sg_vals)}")
    print(f"          (low SG_VAL = high mechanical load / near stall)")

# silence
for _ in range(50): xfer(CHOP_OFF); xfer(SGCS_OFF)

req3.release(); req5.release(); spi.close()
print(f"\n[done] {CHIP_NAME}")
