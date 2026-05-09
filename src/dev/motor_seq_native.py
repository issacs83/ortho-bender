#!/usr/bin/env python3
"""Sequential 1→2→3 with all-native CS topology.

DTS: cs-gpios = <gpio5_13, gpio3_22, gpio5_07>, num-cs=3
spidev1.0 = FEED, spidev1.1 = BEND, spidev1.2 = LIFT
"""
import os, time, sys, signal
import spidev, gpiod

GPIO_CHIP   = "/dev/gpiochip2"
LINE_DIR    = 23
PWM_PATH    = "/sys/class/pwm/pwmchip2/pwm0"
SPI_HZ      = 50_000

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
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
    target_hz = int(sys.argv[2]) if len(sys.argv) > 2 else 4000

    chip = gpiod.Chip(GPIO_CHIP)
    req = chip.request_lines(consumer="motor_seq_native",
        config={LINE_DIR: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW)})

    spi_feed = spidev.SpiDev(); spi_feed.open(1, 0)
    spi_bend = spidev.SpiDev(); spi_bend.open(1, 1)
    spi_lift = spidev.SpiDev(); spi_lift.open(1, 2)
    for s in [spi_feed, spi_bend, spi_lift]:
        s.max_speed_hz = SPI_HZ; s.bits_per_word = 8
        try: s.mode = 3
        except OSError: pass
    print("[spi] all 3 chips native CS (spidev1.0/1.1/1.2)")

    if not os.path.isdir(PWM_PATH):
        with open("/sys/class/pwm/pwmchip2/export",'w') as f: f.write("0\n")
        time.sleep(0.05)
    period = int(1e9 / target_hz); duty = period // 2
    with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
    with open(f"{PWM_PATH}/period",'w') as f: f.write(f"{period}\n")
    with open(f"{PWM_PATH}/duty_cycle",'w') as f: f.write(f"{duty}\n")

    def xfer(s, v): s.xfer2(to_b(v))

    def silence(s, n=200):
        for _ in range(n): xfer(s, CHOPCONF_OFF); xfer(s, SGCSCONF_OFF)

    def init_run(spi_dev, label, sec):
        print(f"\n=== {label} (spidev{['1.0','1.1','1.2'][['FEED','BEND','LIFT'].index(label)]}) ===")
        # init
        seq = [CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF_ON]
        for _ in range(500):
            for v in seq: xfer(spi_dev, v); time.sleep(0.0001)
        print(f"  init done, PWM ON")
        with open(f"{PWM_PATH}/enable",'w') as f: f.write("1\n")
        time.sleep(sec)
        with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
        print(f"  silencing {label}")
        silence(spi_dev)

    stop = {"f": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(f=True))

    # silence all first
    print("[silence all]")
    silence(spi_feed); silence(spi_bend); silence(spi_lift)

    try:
        if not stop["f"]: init_run(spi_feed, "FEED", duration)
        if not stop["f"]: init_run(spi_bend, "BEND", duration)
        if not stop["f"]: init_run(spi_lift, "LIFT", duration)
    finally:
        with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
        for s in [spi_feed, spi_bend, spi_lift]:
            silence(s)
        try: req.release()
        except Exception: pass
        for s in [spi_feed, spi_bend, spi_lift]:
            try: s.close()
            except Exception: pass
        print("\n[done] all silenced")


if __name__ == "__main__": main()
