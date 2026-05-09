#!/usr/bin/env python3
"""motor_test_safe.py — Stack layer motor rotation with HARD SAFETY LIMITS.

Usage: motor_test_safe.py {LIFT|BEND|FEED} [duration_sec=5.0] [hz=4000]

SAFETY GUARDS (cannot be overridden):
  - CS (current scale) <= 19   [burned boards 2026-05-08 with CS=31]
  - TOFF                <= 8   [TOFF>8 thermal damage]
  - CHOPCONF frozen at 0x99548 (verified working)

If the chip refuses to enter RUN, DO NOT attempt aggressive register values.
Use multimeter / oscilloscope passive measurement instead.
"""
import os, sys, time, fcntl, struct, signal
import spidev, gpiod

# ============== HARD SAFETY LIMITS ==============
SAFETY_CS_MAX = 19           # absolute max current scale
SAFETY_TOFF_MAX = 8          # absolute max chopper off-time
CHOPCONF_VERIFIED = 0x99548  # frozen — verified safe
SMARTEN_VERIFIED  = 0xA0000
DRVCONF_VERIFIED  = 0xEF050  # RDSEL=01, VSENSE=1
DRVCTRL_VERIFIED  = 0x00300
SGCSCONF_OFF      = 0xD3F00
CHOP_OFF          = 0x80000

def safe_sgcs(cs):
    if cs > SAFETY_CS_MAX:
        raise ValueError(f"REFUSED: CS={cs} exceeds safety limit {SAFETY_CS_MAX}. "
                         f"This script will not write CS>19. See safety_motor_register_limits.md")
    return 0xD3F00 | (cs & 0x1F)

# Verify CHOPCONF TOFF
_toff = CHOPCONF_VERIFIED & 0xF
if _toff > SAFETY_TOFF_MAX:
    raise ValueError(f"REFUSED: CHOPCONF TOFF={_toff} > {SAFETY_TOFF_MAX}")

# Use CS=19 max safe
CS_OPERATING = 19
SGCSCONF_ON = safe_sgcs(CS_OPERATING)
SEQ = [CHOPCONF_VERIFIED, SMARTEN_VERIFIED, DRVCONF_VERIFIED, DRVCTRL_VERIFIED, SGCSCONF_ON]
# ================================================

CHIP = sys.argv[1].upper() if len(sys.argv) > 1 else 'LIFT'
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
TARGET_HZ = int(sys.argv[3]) if len(sys.argv) > 3 else 4000

# Clamp duration to safe range
if DURATION > 30.0:
    print(f"[safety] duration {DURATION}s clamped to 30s max")
    DURATION = 30.0
if TARGET_HZ > 8000:
    print(f"[safety] hz {TARGET_HZ} clamped to 8000 max")
    TARGET_HZ = 8000

SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40

def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]

LOW = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

# SPI first — resets spi-imx state for clean GPIO request
spi = spidev.SpiDev(); spi.open(1, 0)
spi.max_speed_hz = 50_000; spi.bits_per_word = 8
try: spi.mode = 3
except OSError: pass
fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', 3 | SPI_NO_CS))
spi.xfer2([0,0,0]); time.sleep(0.05)

gpio3 = gpiod.Chip('/dev/gpiochip2')
gpio5 = gpiod.Chip('/dev/gpiochip4')
req3 = gpio3.request_lines(consumer='motortest3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='motortest5', config={
    13: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})

CS_MAP = {'FEED': (req5, 13), 'BEND': (req3, 22), 'LIFT': (req5, 7)}
if CHIP not in CS_MAP:
    print(f"unknown chip {CHIP}. valid: LIFT, BEND, FEED")
    req3.release(); req5.release(); spi.close()
    sys.exit(1)
cs_req, cs_line = CS_MAP[CHIP]

CS_DELAY = 0.0005  # 500us — verified working for BEND chip

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

P = '/sys/class/pwm/pwmchip2/pwm0'

def stop_all():
    """Emergency stop: PWM off + chopper silence on target chip."""
    try:
        with open(f'{P}/enable','w') as f: f.write('0\n')
    except Exception: pass
    try:
        for _ in range(50):
            xfer(CHOP_OFF); xfer(SGCSCONF_OFF)
    except Exception: pass

def sigint_handler(signum, frame):
    print("\n[SIGINT] emergency stop")
    stop_all()
    try: req3.release(); req5.release(); spi.close()
    except Exception: pass
    sys.exit(130)
signal.signal(signal.SIGINT, sigint_handler)
signal.signal(signal.SIGTERM, sigint_handler)

print(f"=== motor_test_safe: {CHIP} (CS={CS_OPERATING}, {DURATION}s @ {TARGET_HZ}Hz) ===")
print(f"[safety] CS_max={SAFETY_CS_MAX}, TOFF_max={SAFETY_TOFF_MAX}, CHOPCONF=0x{CHOPCONF_VERIFIED:05X} frozen")

# Pre-init status
rxv = xfer(SGCSCONF_ON)
print(f"[pre-init]  {parse(rxv)}")

# Init 500x with verified SEQ
print(f"[init] 500x verified SEQ")
for _ in range(500):
    for v in SEQ: xfer(v)

rxv = xfer(SGCSCONF_ON)
print(f"[post-init] {parse(rxv)}")

# Detect early fault — if S2G/OL/OT bits set, abort immediately
status = rxv & 0x7F  # bits 6:0
if status & 0x7E:  # OT|OTPW|S2GA|S2GB|OLA|OLB
    print(f"[ABORT] fault detected: status=0x{status:02X}. Likely board hardware damage.")
    stop_all()
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

# Ramp
print(f"[ramp] 200 -> {TARGET_HZ}Hz over 1.5s")
for i in range(15):
    set_hz(int(200 + (TARGET_HZ-200)*i/14)); time.sleep(1.5/15)

# Run with status monitor + abort on fault
print(f"[RUN] {TARGET_HZ}Hz for {DURATION}s")
t0 = time.time()
abort = False
while time.time()-t0 < DURATION:
    rxv = xfer(SGCSCONF_ON)
    s = rxv & 0x7F
    if s & 0x1E:  # OT|OTPW|S2GA|S2GB present at running time → halt
        print(f"  t={time.time()-t0:4.1f}s  {parse(rxv)} [ABORT — fault]")
        abort = True
        break
    print(f"  t={time.time()-t0:4.1f}s  {parse(rxv)}")
    time.sleep(0.5)

# Ramp down
if not abort:
    print(f"[ramp down]")
    for i in range(10):
        set_hz(int(TARGET_HZ - (TARGET_HZ-200)*i/9)); time.sleep(1.0/10)

stop_all()
req3.release(); req5.release(); spi.close()
print(f"[done] {CHIP}")
