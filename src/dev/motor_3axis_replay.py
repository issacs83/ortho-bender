#!/usr/bin/env python3
"""Faithful replay of working setup from memory:
   motor_3axis_working_2026_05_08.md cycle pattern.

Key differences from motor_chip.py:
  - silence_all (100x for each chip) before each init
  - FEED uses NATIVE CS (cs-gpios via spi-imx), BEND/LIFT use manual+SPI_NO_CS
  - PWM hold 8000 Hz for 6s (not 4000 Hz)
  - Status sampled during run for STST observation
"""
import os, time, sys, fcntl, struct, signal
import spidev, gpiod

SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40

def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)

# Memory-verified registers
CHOPCONF = 0x99548
SMARTEN  = 0xA0000
DRVCONF  = 0xEF050   # RDSEL=01 for SG_VAL readback
DRVCTRL  = 0x00300
SGCSCONF = 0xD3F13   # CS=19, SGT=+63, SFILT=1
CHOP_OFF = 0x80000
SGCS_OFF = 0xD3F00
SEQ = [CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF]

LOW = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

# GPIO setup
gpio3 = gpiod.Chip('/dev/gpiochip2')
gpio5 = gpiod.Chip('/dev/gpiochip4')
req3 = gpio3.request_lines(consumer='replay3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='replay5', config={
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
# Note: NOT requesting line 13 (FEED CS) — that's reserved for spi-imx native CS via cs-gpios

spi = spidev.SpiDev(); spi.open(1, 0)
spi.max_speed_hz = 50_000; spi.bits_per_word = 8
try: spi.mode = 3
except OSError: pass

def set_no_cs(on):
    flags = 3 | (SPI_NO_CS if on else 0)
    fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', flags))

def xfer_feed(v):
    set_no_cs(False)  # native CS via spi-imx + cs-gpios
    rx = spi.xfer2(to_b(v))
    return (rx[0]<<16) | (rx[1]<<8) | rx[2]

def xfer_bend(v):
    set_no_cs(True)
    req3.set_value(22, LOW); time.sleep(0.0001)
    rx = spi.xfer2(to_b(v))
    time.sleep(0.0001); req3.set_value(22, HIGH)
    return (rx[0]<<16) | (rx[1]<<8) | rx[2]

def xfer_lift(v):
    set_no_cs(True)
    req5.set_value(7, LOW); time.sleep(0.0001)
    rx = spi.xfer2(to_b(v))
    time.sleep(0.0001); req5.set_value(7, HIGH)
    return (rx[0]<<16) | (rx[1]<<8) | rx[2]

XFER = {'FEED': xfer_feed, 'BEND': xfer_bend, 'LIFT': xfer_lift}

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
    stst = 'STST' if (s>>7)&1 else 'RUN '
    return f"SG={sg_val:4d} {stst} [{flag_s}]"

def silence_chip(chip_name, n=100):
    f = XFER[chip_name]
    for _ in range(n):
        f(CHOP_OFF); f(SGCS_OFF)

def silence_all(n=100):
    print(f"  [silence_all {n}x each chip]")
    for c in ['FEED', 'BEND', 'LIFT']:
        silence_chip(c, n)

def init_chip(chip_name, n=500):
    f = XFER[chip_name]
    for _ in range(n):
        for v in SEQ: f(v)

def setup_pwm():
    P = '/sys/class/pwm/pwmchip2/pwm0'
    if not os.path.isdir(P):
        with open('/sys/class/pwm/pwmchip2/export','w') as f: f.write('0\n')
        time.sleep(0.05)
    return P

def set_hz(P, h):
    period = int(1e9/h); duty = period//2
    with open(f'{P}/duty_cycle','w') as f: f.write('0\n')
    with open(f'{P}/period','w') as f: f.write(f'{period}\n')
    with open(f'{P}/duty_cycle','w') as f: f.write(f'{duty}\n')
    with open(f'{P}/enable','w') as f: f.write('1\n')

def stop_pwm(P):
    with open(f'{P}/enable','w') as f: f.write('0\n')

def run_chip(chip_name, P, hz_target=8000, hold_sec=6.0):
    print(f"\n=== {chip_name} ===")
    print(f"  [init {chip_name} 500x]")
    init_chip(chip_name)

    # Status check before PWM
    rxv = XFER[chip_name](SGCSCONF)
    print(f"  [pre-PWM] {parse(rxv)}")

    print(f"  [ramp 200 -> {hz_target} over 1.5s]")
    for i in range(15):
        h = int(200 + (hz_target-200)*i/14)
        set_hz(P, h); time.sleep(1.5/15)

    print(f"  [hold {hz_target} Hz for {hold_sec}s, sampling status]")
    t0 = time.time()
    last_print = 0
    while time.time() - t0 < hold_sec:
        time.sleep(0.4)
        if time.time() - t0 - last_print >= 1.0:
            rxv = XFER[chip_name](SGCSCONF)
            print(f"    t={time.time()-t0:4.1f}s  {parse(rxv)}")
            last_print = time.time() - t0

    print(f"  [ramp down]")
    for i in range(10):
        h = int(hz_target - (hz_target-200)*i/9)
        set_hz(P, h); time.sleep(1.0/10)
    stop_pwm(P)

# ====== Main: 2-cycle replay (FEED → BEND → LIFT) ======
P = setup_pwm()
stop_pwm(P)

print("=" * 60)
print("CYCLE 1: FEED → BEND → LIFT")
print("=" * 60)
for chip in ['FEED', 'BEND', 'LIFT']:
    silence_all(100)
    run_chip(chip, P, hz_target=8000, hold_sec=4.0)
silence_all(100)

print("\n" + "=" * 60)
print("CYCLE 2: FEED → BEND → LIFT")
print("=" * 60)
for chip in ['FEED', 'BEND', 'LIFT']:
    silence_all(100)
    run_chip(chip, P, hz_target=8000, hold_sec=4.0)
silence_all(100)

# Cleanup
req3.release(); req5.release(); spi.close()
print("\n[done]")
