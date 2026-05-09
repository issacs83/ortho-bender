#!/usr/bin/env python3
"""SPI write verification — change RDSEL across 0/1/2 and observe readback delta.
If chip receives writes correctly, readback format/value will differ per RDSEL.
If readback is stuck regardless of RDSEL, SPI writes are not landing on the chip.
"""
import sys, time, fcntl, struct, spidev, gpiod

CHIP_NAME = sys.argv[1].upper() if len(sys.argv) > 1 else 'FEED'

SPI_IOC_WR_MODE = 0x40016B01
SPI_NO_CS = 0x40

def to_b(v): return [(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF]

LOW = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

gpio3 = gpiod.Chip('/dev/gpiochip2')
gpio5 = gpiod.Chip('/dev/gpiochip4')
req3 = gpio3.request_lines(consumer='swvfy3', config={
    23: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
    22: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})
req5 = gpio5.request_lines(consumer='swvfy5', config={
    13: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
    7:  gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH),
})

spi = spidev.SpiDev(); spi.open(1, 0)
spi.max_speed_hz = 50_000; spi.bits_per_word = 8
try: spi.mode = 3
except OSError: pass
fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', 3 | SPI_NO_CS))

CS_MAP = {'FEED': (req5, 13), 'BEND': (req3, 22), 'LIFT': (req5, 7)}
cs_req, cs_line = CS_MAP[CHIP_NAME]

def xfer(v):
    cs_req.set_value(cs_line, LOW); time.sleep(0.0001)
    rx = spi.xfer2(to_b(v))
    time.sleep(0.0001); cs_req.set_value(cs_line, HIGH)
    return (rx[0]<<16) | (rx[1]<<8) | rx[2]

print(f"=== {CHIP_NAME} SPI WRITE VERIFICATION ===")
print(f"CS line: gpio{'5' if cs_req is req5 else '3'}_{cs_line}")

# Establish minimum init
xfer(0x99548)  # CHOPCONF
xfer(0xA0000)  # SMARTEN
xfer(0x00300)  # DRVCTRL
xfer(0xD3F13)  # SGCSCONF (CS=19)

# Repeat init multiple times for sticky write
for _ in range(20):
    xfer(0x99548); xfer(0xA0000); xfer(0x00300); xfer(0xD3F13)

# Test 1: RDSEL=00 (MSTEP_VAL readback)
xfer(0xEF040)  # DRVCONF, RDSEL=00
for _ in range(5): xfer(0xD3F13)  # latch new RDSEL
rxv_rdsel0 = []
for i in range(3):
    rxv_rdsel0.append(xfer(0xD3F13))
    time.sleep(0.05)

# Test 2: RDSEL=01 (SG_VALUE readback)
xfer(0xEF050)  # DRVCONF, RDSEL=01
for _ in range(5): xfer(0xD3F13)
rxv_rdsel1 = []
for i in range(3):
    rxv_rdsel1.append(xfer(0xD3F13))
    time.sleep(0.05)

# Test 3: RDSEL=10 (SG + CS readback)
xfer(0xEF060)  # DRVCONF, RDSEL=10
for _ in range(5): xfer(0xD3F13)
rxv_rdsel2 = []
for i in range(3):
    rxv_rdsel2.append(xfer(0xD3F13))
    time.sleep(0.05)

print(f"\n[RDSEL=00 MSTEP_VAL]")
for r in rxv_rdsel0: print(f"  rx=0x{r:05X}")
print(f"[RDSEL=01 SG_VALUE]")
for r in rxv_rdsel1: print(f"  rx=0x{r:05X}")
print(f"[RDSEL=10 SG+CS]")
for r in rxv_rdsel2: print(f"  rx=0x{r:05X}")

# Diagnose: if RDSEL changes affect readback, SPI write works
all_same = (rxv_rdsel0[-1] == rxv_rdsel1[-1] == rxv_rdsel2[-1])
print(f"\n=== VERDICT ===")
if all_same:
    print(f"❌ readback IDENTICAL across RDSEL changes")
    print(f"   → SPI WRITE LIKELY FAILING ({CHIP_NAME} chip not receiving config)")
else:
    print(f"✅ readback CHANGES with RDSEL")
    print(f"   → SPI WRITE WORKING ({CHIP_NAME} chip receives config correctly)")

# silence
for _ in range(50): xfer(0x80000); xfer(0xD3F00)

req3.release(); req5.release(); spi.close()
