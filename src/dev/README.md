# Motor Test Bench — Dev Tools

Diagnostic and test scripts for the i.MX8MP EVK + Veyron 1×2A ×3 (TMC260C-PA) motor stack.

## ⚠️ HARD SAFETY LIMITS (NEVER VIOLATE)

These limits are enforced in `motor_test_safe.py` and `motor_test_all_safe.py` and **must not be relaxed**.

| Field | Max | Reason |
|-------|-----|--------|
| **CS (current scale)** | **19** | CS=31 burned 1/2층 boards (2026-05-08) |
| **TOFF (chopper off-time)** | **8** | TOFF>8 thermal damage |
| **CHOPCONF** | `0x99548` (frozen) | Verified safe pattern |
| **VSENSE=0 + CS>19** | forbidden | Doubles current, instant burn |

**Never sweep / experiment with current/timing values to "see what happens".**
If verified working values don't behave as expected, switch to **passive measurement**
(multimeter / oscilloscope) — never escalate aggressive register writes.

## Primary command (installed permanently on board at `/usr/bin/motor_test`)

```bash
motor_test 1            # LIFT (1층) 5s @ 4kHz
motor_test 2            # BEND (2층) 5s @ 4kHz
motor_test 3            # FEED (3층) 5s @ 4kHz
motor_test all          # 3-axis simultaneous 5s @ 2kHz (slow ramp)
motor_test all 10 3000  # 3-axis 10s @ 3kHz
```

## File index

### Production (installed on board)
- `motor_test` — bash wrapper, installed at `/usr/bin/motor_test`
- `motor_test_safe.py` — single-axis safe rotation, installed at `/usr/local/lib/`
- `motor_test_all_safe.py` — 3-axis simultaneous safe rotation, installed at `/usr/local/lib/`

### Diagnostic (read-only, passive)
- `motor_diag.py` — single-axis diagnostic with PWM
- `motor_diag_csswap.py` — CS line swap test (LIFT↔FEED CS)
- `motor_reg_dump.py` — passive register readback (no PWM)
- `spi_writeverify.py` — RDSEL change verification (SPI write integrity test)

### Reference / historical
- `motor_chip.py` — original single-chip test (100us CS delay, basic)
- `motor_aggressive.py` — SPI-first init + 500us CS delay (the breakthrough pattern)
- `motor_bend_aggressive.py`, `motor_bend_manual.py`, `motor_bend_native.py` — BEND-specific variants
- `motor_chip_only.py`, `motor_seq_native.py` — sequential / single-chip variants
- `motor_all3_native.py`, `motor_all3_phase1.py`, `motor_3axis_replay.py` — 3-axis test variants
- `motor_sdoff_test.py` — SDOFF=1 mode SPI-direct stepping test

### DTS reference (board pinmux)
- `HANDOFF_DTS_WORKFLOW.md` — DTS edit → compile → board flash workflow
- `dtb_active.dts`, `dtb_current.dts`, `dtb_restore.dts`, `dtb_manual_no_csgpios.dts`

## Verified working setup (2026-05-08)

After board burn incident, replaced 1/2층 boards. All 3 axes verified:

| 적층 | Chip | CS GPIO | SG_VAL @ run | Status |
|------|------|---------|--------------|--------|
| 1층 | LIFT | gpio5_07 (ECSPI1_MOSI alt5) | 1008 | RUN [OK] ✓ |
| 2층 | BEND | gpio3_22 (SAI5_RXD1 alt5) | 1008 | RUN [OK] ✓ |
| 3층 | FEED | gpio5_13 (ECSPI2_SS0 alt5) | 1008 | RUN [OK] ✓ |
| ALL | 3-axis | parallel STEP/DIR | 1008 each | RUN [OK] ✓ |

Common parameters:
- CS=19 (~0.6-0.9A RMS), CHOPCONF=0x99548, DRVCONF=0xEF050, DRVCTRL=0x00300
- SPI 50kHz mode 3 + SPI_NO_CS, 500us CS settle
- PWM4 on SAI5_RXFS pad, 4kHz step rate (single) / 2kHz (simultaneous)

## When chip refuses to enter RUN

DO NOT escalate register values. Instead:
1. Stop SPI writes immediately
2. Check VMOT 12V at PSU output
3. Check chip VS (motor supply) pin voltage
4. Check motor connector continuity
5. Check sense resistor (open circuit?)
6. Replace board if hardware fault confirmed
