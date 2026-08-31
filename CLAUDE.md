# ortho-bender

Orthodontic wire-bending robot. i.MX8MP EVK carrier + three TMC260C
stepper drivers, FastAPI backend, React dashboard. A CAD/CAM developer
drives it over HTTP.

`src/app/server` FastAPI + the bench motion engine · `src/app/frontend`
React dashboard · `docs/sdk` the documentation the device serves ·
`tools` operational scripts.

---

## ⛔ Hardware limits — these are not style rules

Two driver boards were destroyed on 2026-05-08 running CS=31.

| Limit | Value | Where enforced |
|---|---|---|
| Coil current scale | **CS ≤ 19** | router (422), service, and `run_cs_for()` at every register write |
| Chopper off-time | **TOFF 1–8** | module-level `assert` at import |
| `CHOPCONF` | **frozen `0x99548`** | written as a constant, never parameterised |

`tests/test_current_safety.py` attacks every path that can energise a
coil and fails loudly if one opens. Run it before touching anything in
`spi_backend.py` or `tmc260c_driver.py`.

The PSU preset (`/api/system/psu`) narrows CS further. Requests above
the ceiling are refused; requests between the ceiling and the PSU cap
are **clamped, not refused** — that is why `run_cs` and
`run_cs_effective` are reported separately.

---

## Reaching the board

**The IP moves.** `192.168.77.2` is a static address on the board's
onboard `eth0` only. Over WiFi or a USB Ethernet adapter it gets a
different one from DHCP. Find it by its API port, not by memory:

```bash
python3 tools/find-board.py            # scans likely subnets for :8000
```

```bash
sshpass -p ortho-bender ssh -o HostKeyAlgorithms=+ssh-rsa root@<ip>
```

The service unit is **`ortho-bender-sdk`**. Its environment
(`OB_MOCK_MODE=false`, `OB_MOTOR_BACKEND=spidev`) lives in the unit
file — starting uvicorn by hand brings the bench up in **mock mode**,
where every motor call silently does nothing.

### Deploy loop

```bash
scp src/app/server/services/spi_backend.py root@<ip>:/opt/ortho-bender/server/services/
ssh root@<ip> 'systemctl restart ortho-bender-sdk'
python3 tools/check-board-sync.py <ip>   # md5 the whole tree against main
```

Docs go to `/opt/ortho-bender/docs/sdk/` and need no restart. The
frontend bundle replaces `/opt/ortho-bender/frontend-dist/`.

---

## Axis conventions

| Axis | ID | cs | Unit | `+` direction | Datum | steps/unit |
|---|---|---|---|---|---|---|
| FEED | 0 | 2 | **mm** of wire | feeds out | none — no switch | 25.4648 *(provisional)* |
| BEND | 1 | 1 | deg | clockwise | limit disc | 23.0167 *(measured)* |
| ROTATE | 2 | — | — | — | not fitted | — |
| LIFT | 3 | 0 | **mm** | **down** | top switch = 0 | 200 *(measured)* |

Axis id and chip-select are **not** the same number. LIFT is axis 3 on
cs 0.

LIFT `+` is downward, 0 at the top switch, +230 mm at the bottom.

Speed ceilings are derived, not configured: `8000 Hz ÷ steps_per_unit`.

---

## Things that look like measurements and are not

Each of these cost real diagnostic time. Do not trust them.

- **`signals.vmot`** — inferred from "the chip answered on SPI". The
  logic side runs off VCC_IO, so it stays `true` with the 12 V motor
  supply completely removed.
- **`drv_status`** — hardcoded `0` on the bench. Real per-chip fault
  flags come from the `/ws/motor/diag` websocket.
- **Register dump** — TMC260C registers are write-only; the dump is the
  driver's shadow copy of what it last wrote.
- **`sg_result`** — StallGuard load, meaningful **only while the shaft
  turns**.
- **Board log timestamps** — the board's clock is years behind (seen at
  `2022-05-25`; RTC sits at `1970-01-01`, `System clock synchronized: no`,
  NTP running but never reaching a server). Every `journalctl` line is
  stamped with that wrong time, so `--since` is useless and **no board log
  can be matched to a host-side measurement by time**. Correlate by
  content, or `date -s` before a debugging session. Check it with
  `ssh root@<ip> date -u` — the same shape of trap as `signals.vmot`: a
  reading that looks authoritative and is not.
- **Never call** `GET /api/motor/diag/register/…` on a TMC260C —
  "reading" is implemented as writing zero to the register.

---

## Behaviour that surprises callers

- **Homing is asynchronous.** `POST /api/motor/home` returns
  immediately. Poll `GET /api/motor/limits` until `homing` is false.
  Any other motion issued meanwhile **cancels the homing**.
- **One axis moves at a time.** All three drivers share one STEP line,
  so every command silences the others first and re-energises them
  after. Consecutive `move_to` calls queue rather than pre-empting.
- **Idle coils are off.** Only the axis being driven is energised.
  LIFT's leadscrew is not self-locking, so it can sink; re-enable
  holding with `PUT /api/motor/protection {"axes":{"3":{"hold_enabled":true}}}`.
- **`/api/motor/enable` and `/disable` dispatch to the M7**, which this
  bench does not run — they do nothing to the chips. Use
  `PUT /api/motor/axis-enable` for per-axis coils and
  `POST /api/motor/reset` to clear a latched driver fault.
- **Three axes reporting the same fault word with `stst` clear** is the
  shared 12 V rail, not three broken motors. Measure VMot at a driver
  terminal.
- **Errors arrive as HTTP 200** with `success: false` and a `code`.

---

## Working on it in VS Code

Install the **Claude Code** extension from the VS Code marketplace, open
this folder, and start a session — it reads this file automatically, so
the limits, the board access and the traps above are already in context.
Running `claude` in the integrated terminal works the same way and will
offer to install the extension if it is missing.

Two habits that matter here more than usual: the bench is real hardware
that has been damaged before, so read `test_current_safety.py` before
changing anything that writes a register; and prefer measuring with the
probes below over reasoning about timing, because several confident
guesses in this codebase turned out wrong.

### Tests

```bash
cd src/app/server && python -m pytest -q     # 171 tests, no hardware needed
cd src/app/frontend && npx tsc --noEmit -p tsconfig.json && npm run build
```

Mock mode (`OB_MOCK_MODE=true`) serves the identical API with no
hardware — build clients against it.

### Measuring instead of guessing

```bash
python3 tools/probe-latency.py http://<ip>:8000       # HTTP floor vs command time
python3 tools/probe-motion-precision.py <ip>          # overshoot vs distance and speed
python3 tools/calibrate-feed.py --base http://<ip>:8000 --mm 100
```

Measure motion cost as **command round-trip time**. A status-polling
probe competes with the motion coroutine on the same event loop and
inflates exactly what it is measuring — that mistake was made here
already.

---

## Open items

- **FEED calibration is provisional.** 1600 PWM cycles/rev is solid
  (1/16 microstepping with DEDGE, two microsteps per cycle); the roller
  diameter has never been measured. `tools/calibrate-feed.py` settles
  both with one measurement.
- **FEED resolution is short of the 0.1 mm target.** One step is
  0.039 mm at the provisional scale, so a 0.1 mm command is 2–3 steps
  and carries ±0.04 mm. Needs ~4× — finer microstepping on FEED (which
  means making `DRVCTRL` per-axis; it is one shared default today) or a
  smaller roller.
- **No simultaneous multi-axis motion.** One hardware PWM STEP line is
  shared. Coordinated motion needs a wiring split plus a device-tree
  pinmux change.
- **StallGuard is tuned unloaded only.** BEND sits usable at `SGT +8`;
  nobody has measured it while actually bending wire, so stall-based
  homing abort stays off.
- **1 ms control is not reachable over HTTP.** Measured floors: 7 ms for
  `/health` on the board itself, 270 ms for the smallest motion command,
  and 123 ms of jitter over WiFi. The M7 coprocessor is the architecture
  for per-tick control; its IPC protocol already exists but is mocked.
