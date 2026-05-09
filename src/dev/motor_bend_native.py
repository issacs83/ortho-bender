#!/usr/bin/env python3
"""BEND single-chip via native CS (spidev1.1) + PWM4 STEP. Sanity check."""
import os, time, sys, signal
import spidev, gpiod

GPIO_CHIP = "/dev/gpiochip2"
LINE_DIR  = 23
PWM_PATH  = "/sys/class/pwm/pwmchip2/pwm0"
SPI_HZ    = 50_000

CHOPCONF     = 0x99548
SMARTEN      = 0xA0000
DRVCONF      = 0xEF040
DRVCTRL      = 0x00300
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)
SGCSCONF_ON  = sgcs(19)
SGCSCONF_OFF = 0xD3F00
CHOPCONF_OFF = 0x80000

LOW  = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE
def to_b(v): return [(v>>16)&0xFF,(v>>8)&0xFF,v&0xFF]


def main():
    target_hz = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    duration  = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0

    chip = gpiod.Chip(GPIO_CHIP)
    req = chip.request_lines(consumer="bend_native",
        config={LINE_DIR: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW)})

    spi_feed = spidev.SpiDev(); spi_feed.open(1, 0)
    spi_bend = spidev.SpiDev(); spi_bend.open(1, 1)
    spi_lift = spidev.SpiDev(); spi_lift.open(1, 2)
    for s in [spi_feed, spi_bend, spi_lift]:
        s.max_speed_hz = SPI_HZ; s.bits_per_word = 8
        try: s.mode = 3
        except OSError: pass

    if not os.path.isdir(PWM_PATH):
        with open("/sys/class/pwm/pwmchip2/export",'w') as f: f.write("0\n")
        time.sleep(0.05)
    period = int(1e9 / target_hz); duty = period // 2
    with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
    with open(f"{PWM_PATH}/period",'w') as f: f.write(f"{period}\n")
    with open(f"{PWM_PATH}/duty_cycle",'w') as f: f.write(f"{duty}\n")
    print(f"[pwm] {target_hz} Hz")

    def xfer(s, v):
        rx = s.xfer2(to_b(v))
        return (rx[0]<<16)|(rx[1]<<8)|rx[2]

    def silence(s, n=200):
        for _ in range(n): xfer(s, CHOPCONF_OFF); xfer(s, SGCSCONF_OFF)

    print("[silence FEED & LIFT]")
    silence(spi_feed); silence(spi_lift)

    print("[init BEND]")
    seq = [CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF_ON]
    for _ in range(500):
        for v in seq: xfer(spi_bend, v); time.sleep(0.0001)
    rxv = xfer(spi_bend, SGCSCONF_ON)
    s = rxv & 0x3FF
    print(f"  status: OT={(s>>1)&1} S2G={(s>>3)&1}{(s>>4)&1} OL={(s>>5)&1}{(s>>6)&1} STST={(s>>7)&1}")

    print("[run] PWM ON")
    with open(f"{PWM_PATH}/enable",'w') as f: f.write("1\n")

    stop = {"f": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(f=True))

    try:
        t0 = time.time()
        while time.time()-t0 < duration and not stop["f"]: time.sleep(0.1)
    finally:
        with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
        for s in [spi_feed, spi_bend, spi_lift]: silence(s)
        try: req.release()
        except Exception: pass
        for s in [spi_feed, spi_bend, spi_lift]:
            try: s.close()
            except Exception: pass
        print("[done]")


if __name__ == "__main__": main()
