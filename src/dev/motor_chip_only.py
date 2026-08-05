#!/usr/bin/env python3
"""Single chip test: feed | bend | lift, with verified setting + DTS DSE X6."""
import os, time, sys, signal
import spidev, gpiod

CHIP_NAME = sys.argv[1] if len(sys.argv) > 1 else "bend"
TARGET_HZ = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
DURATION  = float(sys.argv[3]) if len(sys.argv) > 3 else 0

GPIO_CHIP   = "/dev/gpiochip2"
LINE_DIR    = 23
LINE_BENDCS = 22
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
    chip = gpiod.Chip(GPIO_CHIP)
    req = chip.request_lines(consumer="chip_only",
        config={LINE_DIR:    gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
                LINE_BENDCS: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH)})
    spi_feed = spidev.SpiDev(); spi_feed.open(1, 0)
    spi_lift = spidev.SpiDev(); spi_lift.open(1, 1)
    for s in [spi_feed, spi_lift]:
        s.max_speed_hz = SPI_HZ; s.bits_per_word = 8
        try: s.mode = 3
        except OSError: pass

    if not os.path.isdir(PWM_PATH):
        with open("/sys/class/pwm/pwmchip2/export",'w') as f: f.write("0\n")
        time.sleep(0.05)
    period = int(1e9 / TARGET_HZ); duty = period // 2
    with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
    with open(f"{PWM_PATH}/period",'w') as f: f.write(f"{period}\n")
    with open(f"{PWM_PATH}/duty_cycle",'w') as f: f.write(f"{duty}\n")

    def xfer_feed(v): spi_feed.xfer2(to_b(v))
    def xfer_bend(v):
        req.set_value(LINE_BENDCS, LOW); time.sleep(0.0001)
        spi_feed.xfer2(to_b(v)); time.sleep(0.0001)
        req.set_value(LINE_BENDCS, HIGH)
    def xfer_lift(v): spi_lift.xfer2(to_b(v))

    if   CHIP_NAME == "feed": xfer = xfer_feed; others = [xfer_bend, xfer_lift]
    elif CHIP_NAME == "bend": xfer = xfer_bend; others = [xfer_feed, xfer_lift]
    elif CHIP_NAME == "lift": xfer = xfer_lift; others = [xfer_feed, xfer_bend]
    else: print(f"unknown chip"); return

    print(f"=== {CHIP_NAME.upper()} only @ {TARGET_HZ} Hz ===")
    print("[silence others]")
    for f in others:
        for _ in range(200):
            f(CHOPCONF_OFF); f(SGCSCONF_OFF)
    print(f"[init {CHIP_NAME}]")
    seq = [CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF_ON]
    for _ in range(500):
        for v in seq: xfer(v); time.sleep(0.0001)
    if CHIP_NAME == "bend":
        for _ in range(200):
            xfer_feed(CHOPCONF_OFF); xfer_feed(SGCSCONF_OFF)
    print(f"[run] PWM ON")
    with open(f"{PWM_PATH}/enable",'w') as f: f.write("1\n")

    stop = {"f": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(f=True))
    try:
        if DURATION > 0:
            t0 = time.time()
            while time.time()-t0 < DURATION and not stop["f"]: time.sleep(0.1)
        else:
            while not stop["f"]: time.sleep(0.5)
    finally:
        with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
        for _ in range(200):
            xfer(CHOPCONF_OFF); xfer(SGCSCONF_OFF)
        try: req.set_value(LINE_DIR, LOW); req.set_value(LINE_BENDCS, HIGH); req.release()
        except Exception: pass
        spi_feed.close(); spi_lift.close()
        print(f"[done] {CHIP_NAME} stopped")


if __name__ == "__main__": main()
