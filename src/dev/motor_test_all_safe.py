#!/usr/bin/env python3
"""motor_test_all_safe.py — 3-axis simultaneous rotation with HARD SAFETY LIMITS.

Usage: motor_test_all_safe.py [duration_sec=5.0] [hz=2000]

Strategy:
  1. SPI-first init (resets spi-imx state)
  2. Sequential init of LIFT, BEND, FEED (no peak-current spike)
  3. Slow PWM ramp (3s) to avoid PSU transient
  4. Per-chip fault monitoring → ABORT on any fault
  5. Short duration (max 30s) and conservative hz (default 2000)

SAFETY (cannot override):
  - CS=19 max, TOFF=8 max, CHOPCONF=0x99548 frozen
  - Default hz=2000 (vs single-axis 4000) for PSU safety
  - Fault detected on ANY chip → all chips silenced + PWM off
"""
import os, sys, time, fcntl, struct, signal
import spidev, gpiod

SAFETY_CS_MAX = 19
SAFETY_TOFF_MAX = 8
CHOPCONF_VERIFIED = 0x99548
SMARTEN_VERIFIED  = 0xA0000
DRVCONF_VERIFIED  = 0xEF050
DRVCTRL_VERIFIED  = 0x00300
SGCSCONF_OFF      = 0xD3F00
CHOP_OFF          = 0x80000

def safe_sgcs(cs):
    if cs > SAFETY_CS_MAX:
        raise ValueError(f"REFUSED: CS={cs} > {SAFETY_CS_MAX}")
    return 0xD3F00 | (cs & 0x1F)

assert (CHOPCONF_VERIFIED & 0xF) <= SAFETY_TOFF_MAX, "TOFF check failed"

CS_OPERATING = 19
SGCSCONF_ON = safe_sgcs(CS_OPERATING)
SEQ = [CHOPCONF_VERIFIED, SMARTEN_VERIFIED, DRVCONF_VERIFIED, DRVCTRL_VERIFIED, SGCSCONF_ON]

DURATION  = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
TARGET_HZ = int(sys.argv[2])   if len(sys.argv) > 2 else 2000

if DURATION > 30.0:
    print(f"[safety] duration {DURATION}s clamped to 30s"); DURATION = 30.0
if TARGET_HZ > 4000:
    print(f"[safety] 3-axis simultaneous: hz {TARGET_HZ} clamped to 4000"); TARGET_HZ = 4000
if TARGET_HZ < 200:
    TARGET_HZ = 200

SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40

def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]

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
req3 = gpio3.request_lines(consumer='all_safe3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='all_safe5', config={
    13: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})

CS_MAP = {'LIFT': (req5, 7), 'BEND': (req3, 22), 'FEED': (req5, 13)}
CS_DELAY = 0.0005

def make_xfer(cs_req, cs_line):
    def _xfer(v):
        cs_req.set_value(cs_line, LOW); time.sleep(CS_DELAY)
        rx = spi.xfer2(to_b(v))
        time.sleep(CS_DELAY); cs_req.set_value(cs_line, HIGH)
        time.sleep(CS_DELAY)
        return (rx[0]<<16) | (rx[1]<<8) | rx[2]
    return _xfer

XFER = {chip: make_xfer(req, line) for chip, (req, line) in CS_MAP.items()}

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

def has_fault(rxv):
    return (rxv & 0x7E) != 0  # OT|OTPW|S2GA|S2GB|OLA|OLB|SG

P = '/sys/class/pwm/pwmchip2/pwm0'

def silence_all():
    try:
        with open(f'{P}/enable','w') as f: f.write('0\n')
    except Exception: pass
    for chip in CS_MAP:
        try:
            for _ in range(20):
                XFER[chip](CHOP_OFF); XFER[chip](SGCSCONF_OFF)
        except Exception: pass

def sigint_handler(signum, frame):
    print("\n[SIGINT] emergency stop all axes")
    silence_all()
    try: req3.release(); req5.release(); spi.close()
    except Exception: pass
    sys.exit(130)
signal.signal(signal.SIGINT, sigint_handler)
signal.signal(signal.SIGTERM, sigint_handler)

print(f"=== motor_test_all_safe (3-axis simultaneous) ===")
print(f"[safety] CS={CS_OPERATING}, hz={TARGET_HZ}, duration={DURATION}s, ramp=3s")
print(f"[safety] CS_max={SAFETY_CS_MAX}, TOFF=8, CHOPCONF=0x{CHOPCONF_VERIFIED:05X}")

# Sequential init each chip (no peak current)
print(f"\n[sequential init]")
for chip in ['LIFT', 'BEND', 'FEED']:
    print(f"  init {chip}...")
    for _ in range(500):
        for v in SEQ: XFER[chip](v)
    rxv = XFER[chip](SGCSCONF_ON)
    print(f"  {chip}: {parse(rxv)}")
    if has_fault(rxv):
        print(f"[ABORT] {chip} fault detected before run")
        silence_all()
        req3.release(); req5.release(); spi.close()
        sys.exit(2)

# PWM setup
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

# Slow ramp 3s (vs single 1.5s) for PSU transient safety
RAMP_SEC = 3.0
RAMP_STEPS = 30
print(f"\n[ramp] 200 -> {TARGET_HZ}Hz over {RAMP_SEC}s")
abort = False
for i in range(RAMP_STEPS):
    h = int(200 + (TARGET_HZ-200)*i/(RAMP_STEPS-1))
    set_hz(h)
    # Check faults on every chip during ramp
    for chip in CS_MAP:
        rxv = XFER[chip](SGCSCONF_ON)
        if has_fault(rxv):
            print(f"  [ABORT during ramp] {chip}: {parse(rxv)}")
            abort = True
            break
    if abort: break
    time.sleep(RAMP_SEC/RAMP_STEPS)

if abort:
    silence_all()
    req3.release(); req5.release(); spi.close()
    sys.exit(2)

# Run with continuous fault monitoring
print(f"\n[RUN @ {TARGET_HZ}Hz, monitoring all 3 axes]")
t0 = time.time()
while time.time()-t0 < DURATION:
    line = f"  t={time.time()-t0:4.1f}s "
    fault_chip = None
    for chip in ['LIFT', 'BEND', 'FEED']:
        rxv = XFER[chip](SGCSCONF_ON)
        line += f"{chip}: {parse(rxv)}  "
        if has_fault(rxv):
            fault_chip = chip
    print(line)
    if fault_chip:
        print(f"[ABORT] {fault_chip} fault during run")
        abort = True
        break
    time.sleep(0.5)

if not abort:
    print(f"\n[ramp down]")
    for i in range(20):
        h = int(TARGET_HZ - (TARGET_HZ-200)*i/19)
        set_hz(h); time.sleep(2.0/20)

silence_all()
req3.release(); req5.release(); spi.close()
print(f"[done] all 3 axes")
