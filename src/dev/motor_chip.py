#!/usr/bin/env python3
"""Single-chip motor: FEED | BEND | LIFT — ALL manual CS toggle (LIFT-style).
NO_CS flag prevents spi-imx from toggling any chipselect; Python toggles target GPIO.
"""
import sys, os, time, fcntl, struct, spidev, gpiod

if len(sys.argv) < 2:
    print('Usage: motor_chip.py FEED|BEND|LIFT [duration] [hz]')
    sys.exit(1)

chip_name = sys.argv[1].upper()
duration  = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
hz_target = int(sys.argv[3]) if len(sys.argv) > 3 else 8000

SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40
def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)
SEQ = [0x99548, 0xA0000, 0xEF040, 0x00300, sgcs(19)]
CHOP_OFF = 0x80000; SGCS_OFF = 0xD3F00

LOW = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

# All 3 CS GPIOs
gpio3 = gpiod.Chip('/dev/gpiochip2')   # GPIO3 bank
gpio5 = gpiod.Chip('/dev/gpiochip4')   # GPIO5 bank
req3 = gpio3.request_lines(consumer='all_manual_g3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),     # DIR
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),    # BEND CS idle
})
req5 = gpio5.request_lines(consumer='all_manual_g5', config={
    13: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),    # FEED CS idle (was cs-gpios)
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),    # LIFT CS idle
})

spi = spidev.SpiDev(); spi.open(1, 0)
spi.max_speed_hz = 50_000; spi.bits_per_word = 8
try: spi.mode = 3
except OSError: pass
# NO_CS for all chips — Python toggles all CS manually
fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', 3 | SPI_NO_CS))

# Map chip to (gpio request object, line number)
CS_MAP = {
    'FEED': (req5, 13),   # gpio5_13
    'BEND': (req3, 22),   # gpio3_22
    'LIFT': (req5, 7),    # gpio5_07
}
if chip_name not in CS_MAP:
    print(f'unknown chip {chip_name}'); sys.exit(1)
cs_req, cs_line = CS_MAP[chip_name]

def xfer(v):
    cs_req.set_value(cs_line, LOW); time.sleep(0.0001)
    rx = spi.xfer2(to_b(v))
    time.sleep(0.0001); cs_req.set_value(cs_line, HIGH)
    return rx

print(f'[{chip_name}] CS GPIO line {cs_line} on {"gpio3" if cs_req is req3 else "gpio5"} — manual toggle')
print(f'[{chip_name}] init')
for _ in range(500):
    for v in SEQ: xfer(v); time.sleep(0.0001)

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

print(f'[{chip_name}] ramp 200 -> {hz_target} over 1.5s')
for i in range(15):
    set_hz(int(200 + (hz_target-200)*i/14)); time.sleep(1.5/15)

print(f'[{chip_name}] hold {hz_target}Hz for {duration}s')
set_hz(hz_target); time.sleep(duration)

print(f'[{chip_name}] ramp down')
for i in range(10):
    set_hz(int(hz_target - (hz_target-200)*i/9)); time.sleep(1.0/10)
with open(f'{P}/enable','w') as f: f.write('0\n')
for _ in range(50): xfer(CHOP_OFF); xfer(SGCS_OFF)
req3.release(); req5.release(); spi.close()
print(f'[{chip_name}] done')
