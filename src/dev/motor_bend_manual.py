#!/usr/bin/env python3
"""BEND single-chip — MORNING WORKING method:
- spidev1.0 = FEED native CS (ECSPI2 SS0)
- BEND CS = manual GPIO toggle (gpiochip2 line 22 = gpio3_22)
- DIR = gpiochip2 line 23 manual LOW
- STEP = PWM4 8 kHz
"""
import os, time, sys, signal
import spidev, gpiod

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
CHOPCONF_OFF = 0x80000
SGCSCONF_OFF = 0xD3F00

LOW  = gpiod.line.Value.INACTIVE
HIGH = gpiod.line.Value.ACTIVE
def to_b(v): return [(v>>16)&0xFF,(v>>8)&0xFF,v&0xFF]


def main():
    target_hz = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    duration  = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0

    chip = gpiod.Chip(GPIO_CHIP)
    req = chip.request_lines(consumer="bend_manual",
        config={LINE_DIR:    gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=LOW),
                LINE_BENDCS: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=HIGH)})

    spi = spidev.SpiDev(); spi.open(1, 0)
    spi.max_speed_hz = SPI_HZ; spi.bits_per_word = 8
    try: spi.mode = 3
    except OSError: pass
    # Apply SPI_NO_CS via raw ioctl — spidev Python lib only accepts mode 0..3,
    # but the kernel SPI_IOC_WR_MODE ioctl accepts the full 8-bit flags including
    # SPI_NO_CS (0x40). This stops spi-imx from toggling FEED CS (gpio5_13)
    # on every xfer; only the manual BEND CS (gpio3_22) drives chip select.
    import fcntl, struct
    SPI_IOC_WR_MODE = 0x40016B01
    SPI_NO_CS = 0x40
    flags = 3 | SPI_NO_CS
    try:
        fcntl.ioctl(spi.fileno(), SPI_IOC_WR_MODE, struct.pack('B', flags))
        print(f"[spi] mode=0x{flags:02X} (mode3 + NO_CS) via ioctl")
    except Exception as e:
        print(f"[spi] NO_CS ioctl failed: {e}, falling back to mode 3")
    print("[cs ] BEND manual CS (gpio3_22) only — FEED CS NOT toggled")

    if not os.path.isdir(PWM_PATH):
        with open("/sys/class/pwm/pwmchip2/export",'w') as f: f.write("0\n")
        time.sleep(0.05)

    def xfer_feed(v):
        rx = spi.xfer2(to_b(v))
        return (rx[0]<<16)|(rx[1]<<8)|rx[2]
    def xfer_bend(v):
        req.set_value(LINE_BENDCS, LOW); time.sleep(0.0001)
        rx = spi.xfer2(to_b(v))
        time.sleep(0.0001); req.set_value(LINE_BENDCS, HIGH)
        return (rx[0]<<16)|(rx[1]<<8)|rx[2]

    def parse(rxv):
        s = rxv & 0xFF
        return f"OT={(s>>1)&1} S2G={(s>>3)&1}{(s>>4)&1} OL={(s>>5)&1}{(s>>6)&1} STST={(s>>7)&1}"

    print("[silence FEED]")
    for _ in range(200): xfer_feed(CHOPCONF_OFF); xfer_feed(SGCSCONF_OFF)

    print("[init BEND via manual CS]")
    seq = [CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF_ON]
    for v in seq:
        rxv = xfer_bend(v)
        print(f"  0x{v:05X} → 0x{rxv:05X}  {parse(rxv)}")
    for _ in range(500):
        for v in seq: xfer_bend(v); time.sleep(0.0001)
    rxv = xfer_bend(SGCSCONF_ON)
    print(f"[init done] {parse(rxv)}")

    def set_hz(hz):
        period=int(1e9/hz); duty=period//2
        with open(f"{PWM_PATH}/duty_cycle",'w') as f: f.write("0\n")
        with open(f"{PWM_PATH}/period",'w') as f: f.write(f"{period}\n")
        with open(f"{PWM_PATH}/duty_cycle",'w') as f: f.write(f"{duty}\n")
        with open(f"{PWM_PATH}/enable",'w') as f: f.write("1\n")

    print(f"[ramp] 200 -> {target_hz} Hz over 3s")
    for i in range(30):
        set_hz(int(200 + (target_hz-200)*i/29)); time.sleep(3/30)

    print(f"[hold] {target_hz} Hz for {duration}s")
    set_hz(target_hz)

    stop = {"f": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(f=True))

    try:
        t0 = time.time()
        last = 0
        while time.time()-t0 < duration and not stop["f"]:
            time.sleep(0.5)
            now = time.time()-t0
            if now - last >= 2:
                rxv = xfer_bend(SGCSCONF_ON)
                print(f"  t={now:.1f}s  0x{rxv:05X}  {parse(rxv)}")
                last = now
        print("[ramp down]")
        for i in range(15):
            set_hz(int(target_hz - (target_hz-200)*i/14)); time.sleep(1.5/15)
    finally:
        with open(f"{PWM_PATH}/enable",'w') as f: f.write("0\n")
        for _ in range(100):
            xfer_bend(CHOPCONF_OFF); xfer_bend(SGCSCONF_OFF)
        try: req.set_value(LINE_BENDCS, HIGH); req.release()
        except Exception: pass
        spi.close()
        print("[done]")


if __name__ == "__main__": main()
