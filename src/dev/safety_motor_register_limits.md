# Motor Driver Register Safety Limits (AUTHORITATIVE)

> Referenced by `tmc260c_driver.py`, `spi_backend.py`, `diag_service.py`.
> This file did not exist in the tree even though three modules cited it —
> reconstructed 2026-08-03 from the incident history and the enforcement
> code itself.

## Incident — 2026-05-08 board burn

During a register sweep test, **CS=31 + TOFF=15** was applied to the
Veyron 1×2A (TMC260C-PA) driver boards via raw SPI. Two boards (1층/2층)
burned. Root cause: coil current scale and chopper-off time both at
maximum → thermal runaway in the driver stage; the 12 V bench PSU kept
feeding the short.

## Hard limits (never exceed — enforced in code)

| Parameter | Register | Limit | Enforced at |
|---|---|---|---|
| Current scale CS | SGCSCONF bits [4:0] | **≤ 19** | `Tmc260cDriver.set_current`, `diag_service._validate_tmc260c_write`, `SpidevMotorBackend._sgcs_on_value` |
| Chopper TOFF | CHOPCONF bits [3:0] | **1–8** (0 = intentional silence) | same three layers |
| CHOPCONF default | — | frozen `0x99548` | import-time asserts in `tmc260c_driver.py` + `spi_backend.py` |
| SGCSCONF default | — | `0xD3F13` (CS=19, SGT=+63, SFILT=1) | import-time asserts |

## PSU-derived caps (narrower than the hard limit)

The hard CS≤19 limit assumes a supply that can actually feed it. The
active PSU preset (Settings → PSU) narrows the cap further:

| Preset | cs_cap |
|---|---|
| 12 V / 2.0 A | 12 |
| 12 V / 2.9 A (bench default) | 14 |
| 12 V / 5.0 A | 17 |
| 12 V / 8.0 A | 19 |
| 24 V / 3.0 A | 19 |

Enforcement paths:
1. **Frontend sliders** — clamp + toast (`MotorPage`, `PSU_PRESETS`).
2. **`/api/motor/diag/register` writes** — `UnsafeRegisterWrite` guard in
   `diag_service.py` consults `PsuService.cs_cap`.
3. **Jog/move init path** — `SpidevMotorBackend.apply_current_cap()` is
   fed from `PsuService` at startup and on every PSU change, so
   `_init_chip()` writes a supply-appropriate SGCSCONF. (Added
   2026-08-03; before that the init path wrote CS=19 unconditionally.)

## Speed tuning policy

Motor speed/responsiveness improvements MUST come from the step path,
never from current:

- Microstepping (DRVCTRL MRES — 1/16 default since 2026-08-03, was 1/256)
- PWM/ramp behaviour (`_RAMP_ACCEL_HZ_PER_S`, glitch-free period writes)
- SPI transaction latency (settle times, init cycle counts)
- Supply voltage (24 V preset) or mechanical gearing

Raising CS or TOFF beyond the tables above is prohibited regardless of
the requested speed target.
