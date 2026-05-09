#!/usr/bin/env python3
"""3-axis motor — ALL chips use native CS (spidev1.0/1.1/1.2). No manual CS toggle.

DTS cs-gpios = <gpio5_13 (FEED), gpio3_22 (BEND), gpio5_07 (LIFT)>
spidev1.0 = FEED, spidev1.1 = BEND, spidev1.2 = LIFT — same SPI mechanism for all.
"""
import os, time, sys, signal
import spidev, gpiod

GPIO_CHIP   = "/dev/gpiochip2"
LINE_DIR    = 23
PWM_PATH    = "/sys/class/pwm/pwmchip2/pwm0"
SPI_HZ      = 50_000

CHOPCONF     = 0x99548   # verified
SMARTEN      = 0xA0000   # CoolStep OFF
DRVCONF      = 0xEF040   # SLP=11/11, VSENSE=0, DIS_S2G=1, RDSEL=2
DRVCTRL      = 0x00300   # 256 microstep + DEDGE
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)
SGCSCONF_ON  = sgcs(19)   # ~0.9 A RMS
SGCSCONF_OFF = 0xD3F00
CHOPCONF_OFF = 0x80000

LOW  = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE

def to_b(v): return [(v>>16)&0xFF,(v>>8)&0xFF,v&0xFF]


def main():
    target_hz = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    duration  = float(sys.argv[2]) if len(sys.argv) > 2 else 0
    dir_arg   = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    DIR_LEVEL = HIGH if dir_arg else LOW

    # Only DIR is manual (no chip CS manual)
    chip = gpiod.Chip(GPIO_CHIP)
    req = chip.request_lines(consumer="motor_native",
        config={LINE_DIR: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=DIR_LEVEL)})

    # All 3 chips use native CS via spidev
    spi_feed = spidev.SpiDev(); spi_feed.open(1, 0)   # gpio5_13
    spi_bend = spidev.SpiDev(); spi_bend.open(1, 1)   # gpio3_22
    spi_lift = spidev.SpiDev(); spi_lift.open(1, 2)   # gpio5_07
    for s in [spi_feed, spi_bend, spi_lift]:
        s.max_speed_hz = SPI_HZ; s.bits_per_word = 8
        try: s.mode = 3
        except OSError: pass
    print("[spi] /dev/spidev1.0 (FEED), 1.1 (BEND), 1.2 (LIFT) — native CS auto")

    if not os.path.isdir(PWM_PATH):
        with open("/sys/class/pwm/pwmchip2/export",'w') as f: f.write("0\n")
        time.sleep(0.05)
    period = int(1e9 / target_hz); duty = period // 2
    with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
    with open(f"{PWM_PATH}/period",'w') as f: f.write(f"{period}\n")
    with open(f"{PWM_PATH}/duty_cycle",'w') as f: f.write(f"{duty}\n")
    print(f"[pwm] {target_hz} Hz, disabled")
    print(f"[gpio] DIR={'HIGH(rev)' if dir_arg else 'LOW(fwd)'}")

    def xfer(s, v):
        rx = s.xfer2(to_b(v))
        return (rx[0]<<16)|(rx[1]<<8)|rx[2]

    def parse(rxv):
        s = rxv & 0x3FF
        return f"OT={(s>>1)&1} S2G={(s>>3)&1}{(s>>4)&1} OL={(s>>5)&1}{(s>>6)&1} STST={(s>>7)&1} ms={(rxv>>10)&0x3FF}"

    def init_chip(spi_dev, label, n=500):
        seq = [CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF_ON]
        for _ in range(n):
            for v in seq: xfer(spi_dev, v); time.sleep(0.0001)
        rxv = xfer(spi_dev, SGCSCONF_ON)
        print(f"  [{label}] {parse(rxv)}")

    print("\n[INIT] Each chip with own SPI bus (identical mechanism)")
    init_chip(spi_feed, "FEED")
    init_chip(spi_bend, "BEND")
    init_chip(spi_lift, "LIFT")

    time.sleep(0.2)
    print("[run] PWM ON")
    with open(f"{PWM_PATH}/enable",'w') as f: f.write("1\n")

    stop = {"f": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(f=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(f=True))

    try:
        if duration > 0:
            t0 = time.time()
            while time.time()-t0 < duration and not stop["f"]: time.sleep(0.1)
        else:
            while not stop["f"]: time.sleep(0.5)
    finally:
        with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
        for s in [spi_feed, spi_bend, spi_lift]:
            for _ in range(100):
                xfer(s, CHOPCONF_OFF); xfer(s, SGCSCONF_OFF)
        try: req.set_value(LINE_DIR, LOW); req.release()
        except Exception: pass
        for s in [spi_feed, spi_bend, spi_lift]:
            try: s.close()
            except Exception: pass
        print("[done] silenced")


if __name__ == "__main__": main()
