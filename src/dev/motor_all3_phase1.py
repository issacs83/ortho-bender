#!/usr/bin/env python3
"""
Phase 1: 종합 SW fix
- VSENSE=1 (current 절반, transient 감소)
- CS=27 + VSENSE=1 → ~0.7 A RMS
- SPI clock 2 MHz (Klipper-style)
- Init order: DRVCTRL → CHOPCONF → SMARTEN → SGCSCONF → DRVCONF (Klipper)
- CHOPCONF Klipper-style: TBL=2, HEND=3, HSTRT=3, TOFF=4
- DTS pad config DSE X6 적용 가정 (BEND CS, DIR, STEP)
"""
import os, time, sys, signal
import spidev, gpiod

GPIO_CHIP   = "/dev/gpiochip2"
LINE_DIR    = 23
LINE_BENDCS = 22
PWM_PATH    = "/sys/class/pwm/pwmchip2/pwm0"
SPI_HZ      = 50_000   # verified slow SPI (DTS DSE X6 적용 상태)

# Verified working setting (motor_bend_pwm.py BEND single rotated)
CHOPCONF     = 0x99548   # TBL=54, HEND=10, HSTRT=4, TOFF=8
SMARTEN      = 0xA0000   # CoolStep OFF
DRVCONF      = 0xEF040   # SLP=11/11, VSENSE=0, DIS_S2G=1, RDSEL=2 (verified)
DRVCTRL      = 0x00300   # 256 microstep + DEDGE
def sgcs(cs): return 0xD3F00 | (cs & 0x1F)
SGCSCONF_ON  = sgcs(27)   # CS=27, VSENSE=0 → ~1.05 A RMS (stronger torque for multi-chip)
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

    chip = gpiod.Chip(GPIO_CHIP)
    req = chip.request_lines(consumer="motor_phase1",
        config={LINE_DIR:    gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=DIR_LEVEL),
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
    period = int(1e9 / target_hz); duty = period // 2
    with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
    with open(f"{PWM_PATH}/period",'w') as f: f.write(f"{period}\n")
    with open(f"{PWM_PATH}/duty_cycle",'w') as f: f.write(f"{duty}\n")
    print(f"[pwm] {target_hz} Hz, disabled")
    print(f"[gpio] DIR={'HIGH(rev)' if dir_arg else 'LOW(fwd)'}")

    def xfer_feed(v):
        rx = spi_feed.xfer2(to_b(v))
        return (rx[0]<<16)|(rx[1]<<8)|rx[2]
    def xfer_bend(v):
        req.set_value(LINE_BENDCS, LOW); time.sleep(0.00005)
        rx = spi_feed.xfer2(to_b(v)); time.sleep(0.00005)
        req.set_value(LINE_BENDCS, HIGH)
        return (rx[0]<<16)|(rx[1]<<8)|rx[2]
    def xfer_lift(v):
        rx = spi_lift.xfer2(to_b(v))
        return (rx[0]<<16)|(rx[1]<<8)|rx[2]

    def parse(rxv):
        s = rxv & 0x3FF
        return f"OT={(s>>1)&1} S2G={(s>>3)&1}{(s>>4)&1} OL={(s>>5)&1}{(s>>6)&1} STST={(s>>7)&1} ms={(rxv>>10)&0x3FF}"

    # Verified working init order (motor_bend_pwm.py)
    def init_chip(xfer_fn, label, n=500):
        seq = [CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF_ON]
        for _ in range(n):
            for v in seq: xfer_fn(v)
        # status check
        rxv = xfer_fn(SGCSCONF_ON)
        print(f"  [{label}] init done — {parse(rxv)}")

    print("\n[INIT] All 3 chips with Klipper init order + Phase 1 settings")
    init_chip(xfer_lift, "LIFT")
    init_chip(xfer_feed, "FEED")
    init_chip(xfer_bend, "BEND")

    time.sleep(0.2)
    print("[run] PWM ON")
    with open(f"{PWM_PATH}/enable",'w') as f: f.write("1\n")

    stop = {"f": False}
    signal.signal(signal.SIGINT,  lambda *_: stop.update(f=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(f=True))

    try:
        if duration > 0:
            t0 = time.time()
            while time.time() - t0 < duration and not stop["f"]:
                time.sleep(0.1)
        else:
            while not stop["f"]:
                time.sleep(0.5)
    finally:
        with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
        for f in [xfer_feed, xfer_bend, xfer_lift]:
            for _ in range(100):
                f(CHOPCONF_OFF); f(SGCSCONF_OFF)
        try: req.set_value(LINE_DIR, LOW); req.set_value(LINE_BENDCS, HIGH); req.release()
        except Exception: pass
        spi_feed.close(); spi_lift.close()
        print("[done] silenced")


if __name__ == "__main__":
    main()
