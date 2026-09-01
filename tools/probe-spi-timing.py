#!/usr/bin/env python3
"""Find the real SPI framing margin on the TMC260C bench — chopper OFF.

WHY THIS EXISTS
---------------
Every motion command spends ~36 ms writing five bytes' worth of registers,
and almost none of that is bus traffic:

    _init_chip fast re-enable   10 frames   17 ms
    _read_status                 1 frame     2 ms
    _finish_axis / _silence     10 frames   17 ms

A frame costs 3 x _CS_SETTLE_S (1.5 ms of time.sleep) plus 24 bits at
spi_speed_hz (480 us at the configured 50 kHz).  The TMC260C datasheet
wants ~100 ns of CS setup and takes SCK up to 4 MHz, so both numbers are
three orders of magnitude of margin that nobody has ever measured.  This
script measures them.

SAFETY
------
The chopper is never enabled.  Every CHOPCONF this script transmits has
TOFF=0, which is the one bit that makes coil current possible; two driver
boards were destroyed on 2026-05-08 by current, not by SPI.  In addition:

  * the sweep starts from, and returns to, the known-good 500 us / 50 kHz
    framing after EVERY grid point, and re-verifies there;
  * a failed grid point aborts that point immediately and recovers;
  * the finally block restores safe framing and re-silences all chips
    even on Ctrl-C or an exception.

VERIFICATION
------------
TMC260C registers are write-only, so "did the write land" cannot be asked
directly.  Two indirect checks are used instead, and neither accepts a
merely non-empty answer:

  1. FRAMING.  A reference status word is captured at the known-good
     500 us / 50 kHz.  The shaft is not turning, so SG is constant and the
     word is stable (0xFC800 here = SG 1010, the same value the REST API
     reports).  A sweep point passes only if EVERY response equals that
     reference exactly.  Rejecting only 0x00000/0xFFFFF would pass
     corrupted-but-plausible words; an exact match will not.

  2. LATCHING.  DRVCONF's RDSEL field selects what the NEXT response
     contains: RDSEL=01 -> StallGuard value, RDSEL=00 -> microstep
     position.  These read differently on a stationary motor, so writing
     DRVCONF once with a new RDSEL and seeing the response format change
     proves a single 20-bit datagram latched.  That is the question behind
     _REENABLE_CYCLES / _SILENCE_CYCLES = 5: the same shift register
     latches every register, so if one frame is enough for DRVCONF it is
     enough for CHOPCONF and SGCSCONF.

USAGE
-----
The running server owns the GPIO lines exclusively, so stop it first:

    systemctl stop ortho-bender-sdk
    python3 /tmp/probe-spi-timing.py
    systemctl start ortho-bender-sdk
"""
import argparse
import os
import socket
import sys
import time

sys.path.insert(0, "/opt/ortho-bender")

import asyncio

from server.services import spi_backend as sb
from server.services.spi_backend import (
    SpidevMotorBackend, CHOPCONF_DEFAULT, SGCSCONF_DEFAULT, DRVCONF_DEFAULT,
    SAFETY_CS_MAX,
)

# ---- register words: TOFF=0 in every CHOPCONF we ever transmit ----------
CHOP_OFF = 0x80000                       # TOFF=0 -> chopper disabled
assert (CHOP_OFF & 0xF) == 0, "harness would enable the chopper"
assert (CHOPCONF_DEFAULT & 0xF) <= 8

SGCS_BASE = SGCSCONF_DEFAULT & ~0x1F     # SGT/SFILT preserved, CS cleared
DRVCONF_SG   = (DRVCONF_DEFAULT & ~0x30) | 0x10  # RDSEL=01 -> SG value
DRVCONF_SE   = (DRVCONF_DEFAULT & ~0x30) | 0x20  # RDSEL=10 -> SG + SE (CS)
DRVCONF_STEP = (DRVCONF_DEFAULT & ~0x30)         # RDSEL=00 -> microstep pos

SAFE_SETTLE_S = 0.0005
SAFE_CLOCK_HZ = 50_000

SETTLES_US = (500, 200, 100, 50, 20, 10)
CLOCKS_HZ  = (50_000, 100_000, 250_000, 500_000, 1_000_000, 2_000_000)


def _sgcs(cs_value: int) -> int:
    cs_value = max(0, min(int(cs_value), SAFETY_CS_MAX))
    return SGCS_BASE | cs_value


def _tx(be, tag: int, value: int) -> bytes:
    d = be._encode(tag, value)
    return bytes([(d >> 16) & 0xFF, (d >> 8) & 0xFF, d & 0xFF])


def _word(rx: bytes) -> int:
    return ((rx[0] << 16) | (rx[1] << 8) | rx[2]) & 0xFFFFF


def _valid(w: int) -> bool:
    """0x00000 = nothing driving MISO, 0xFFFFF = line floating high."""
    return w not in (0x00000, 0xFFFFF)


class Harness:
    def __init__(self, be):
        self.be = be
        self.se_tracks_cs = None      # decided by the first probe
        self.ref_sg: dict[int, int] = {}    # stable RDSEL=01 word per cs
        self.ref_step: dict[int, int] = {}  # stable RDSEL=00 word per cs

    async def silence(self, cs: int, cycles: int = 5) -> list[bytes]:
        """Chopper off + zero current. The safest sequence on this bench."""
        return await self.be.spi_transfer_batch(
            cs, [_tx(self.be, 0x04, CHOP_OFF),
                 _tx(self.be, 0x06, _sgcs(0))] * cycles)

    async def read_status(self, cs: int, rdsel_word: int) -> int:
        """Two frames: the first selects RDSEL, the second reads under it."""
        rx = await self.be.spi_transfer_batch(
            cs, [_tx(self.be, 0x07, rdsel_word)] * 2)
        return _word(rx[-1])

    async def read_se(self, cs: int) -> int:
        """Effective current scale as the chip reports it (RDSEL=10, bits 9:5)."""
        return (await self.read_status(cs, DRVCONF_SE) >> 5) & 0x1F

    async def set_cs_and_read(self, cs: int, want: int, cycles: int) -> int:
        """Write SGCSCONF `cycles` times, then read the scale back."""
        await self.be.spi_transfer_batch(
            cs, [_tx(self.be, 0x06, _sgcs(want))] * cycles)
        return await self.read_se(cs)

    async def recover(self, cs: int) -> bool:
        """Return to known-good framing, re-silence, confirm the chip talks."""
        sb._CS_SETTLE_S = SAFE_SETTLE_S
        self.be._spi.max_speed_hz = SAFE_CLOCK_HZ
        await self.silence(cs, cycles=5)
        w = await self.read_status(cs, DRVCONF_SG)
        return w == self.ref_sg.get(cs, w) and _valid(w)

    async def capture_reference(self, cs: int, n: int = 12) -> bool:
        """Reference words at known-good framing. The shaft is stationary,
        so both must be constant; if they are not, nothing downstream can
        use an exact-match criterion and we say so instead of pretending."""
        sb._CS_SETTLE_S = SAFE_SETTLE_S
        self.be._spi.max_speed_hz = SAFE_CLOCK_HZ
        await self.silence(cs)
        sg = {await self.read_status(cs, DRVCONF_SG) for _ in range(n)}
        st = {await self.read_status(cs, DRVCONF_STEP) for _ in range(n)}
        await self.read_status(cs, DRVCONF_SG)      # leave RDSEL as found
        if len(sg) != 1 or len(st) != 1 or not _valid(next(iter(sg))):
            print(f"  cs={cs} reference NOT stable: "
                  f"sg={[hex(x) for x in sg]} step={[hex(x) for x in st]}")
            return False
        self.ref_sg[cs] = next(iter(sg))
        self.ref_step[cs] = next(iter(st))
        distinct = self.ref_sg[cs] != self.ref_step[cs]
        note = "distinguishable" if distinct else "IDENTICAL - no latch test"
        print(f"  cs={cs} reference stable: RDSEL=01 -> 0x{self.ref_sg[cs]:05X}"
              f"   RDSEL=00 -> 0x{self.ref_step[cs]:05X}   ({note})")
        return distinct


async def probe_se_support(h: Harness, chips: list[int]) -> bool:
    """Does SE actually follow CS on this bench? Decides how strong the
    later verdicts can be. Chopper stays off, so CS=14 draws nothing."""
    print("=== does the chip report its current scale back? (RDSEL=10) ===")
    ok_any = False
    for cs in chips:
        await h.silence(cs)
        lo = await h.set_cs_and_read(cs, 0, 5)
        hi = await h.set_cs_and_read(cs, 14, 5)
        await h.silence(cs)
        back = await h.read_se(cs)
        tracks = (lo == 0 and hi == 14 and back == 0)
        ok_any |= tracks
        print(f"  cs={cs}  CS=0 -> SE={lo:2d}   CS=14 -> SE={hi:2d}   "
              f"re-silenced -> SE={back:2d}   {'TRACKS' if tracks else 'no'}")
    if not ok_any:
        print("  -> SE does not mirror CS here; verdicts below are framing"
              " integrity only (a valid, stable status word), not proof the"
              " write latched.")
    else:
        print("  -> closed loop available: a write that does not land shows up.")
    return ok_any


async def grid_point(h: Harness, cs: int, settle_us: int, clock_hz: int,
                     trials: int) -> tuple[bool, float, str]:
    """One (settle, clock) point. Returns (passed, ms_per_10_frames, detail).

    Pass = every response is bit-for-bit the reference word captured at the
    known-good framing. A corrupted frame that still looks like a plausible
    status word fails here; it would not have failed a "not 0x0/0xFFFFF" test.
    """
    ref = h.ref_sg[cs]
    sb._CS_SETTLE_S = settle_us / 1e6
    h.be._spi.max_speed_hz = clock_hz
    bad = 0
    seen: set[int] = set()
    t0 = time.perf_counter()
    try:
        for _ in range(trials):
            w = await h.read_status(cs, DRVCONF_SG)
            if w != ref:
                bad += 1
                seen.add(w)
    except Exception as exc:
        return False, 0.0, f"exception: {exc}"
    finally:
        elapsed = time.perf_counter() - t0
        recovered = await h.recover(cs)
    per10 = (elapsed / (trials * 2)) * 10 * 1000.0
    if not recovered:
        return False, per10, "did not recover at known-good framing"
    if bad:
        got = ", ".join(f"0x{x:05X}" for x in sorted(seen)[:3])
        return False, per10, f"{bad}/{trials} mismatched (saw {got})"
    return True, per10, f"{trials}/{trials} == 0x{ref:05X}"


async def cycles_point(h: Harness, cs: int, cycles: int,
                       trials: int) -> tuple[bool, str]:
    """Does `cycles` repetitions of a DRVCONF write latch on the first try?

    Alternates RDSEL between 01 (StallGuard) and 00 (microstep position).
    The response format is set by the DRVCONF that was just written, so a
    response in the OLD format means the write did not take. This is the
    only latch evidence a write-only register set can give.
    """
    bad = 0
    for i in range(trials):
        want_sg = bool(i & 1)
        word = DRVCONF_SG if want_sg else DRVCONF_STEP
        expect = h.ref_sg[cs] if want_sg else h.ref_step[cs]
        await h.be.spi_transfer_batch(
            cs, [_tx(h.be, 0x07, word)] * cycles)
        rx = await h.be.spi_transfer_batch(cs, [_tx(h.be, 0x07, word)])
        if _word(rx[-1]) != expect:
            bad += 1
    await h.silence(cs)
    await h.read_status(cs, DRVCONF_SG)
    return bad == 0, f"{trials - bad}/{trials} latched on the first frame"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--chips", default="0,1,2",
                    help="cs list; 1=BEND is the pad the 500 us was set for")
    args = ap.parse_args()

    s = socket.socket()
    s.settimeout(0.5)
    if s.connect_ex(("127.0.0.1", 8000)) == 0:
        print("ortho-bender-sdk is running and owns the GPIO lines.\n"
              "  systemctl stop ortho-bender-sdk   # then re-run", file=sys.stderr)
        return 2
    s.close()

    chips = [int(x) for x in args.chips.split(",") if x.strip()]
    be = SpidevMotorBackend()
    await be.open()
    h = Harness(be)
    try:
        print(f"baseline: settle={SAFE_SETTLE_S*1e6:.0f}us  "
              f"clock={SAFE_CLOCK_HZ//1000}kHz  chips={chips}\n")
        print("=== reference words at known-good framing ===")
        latch_ok = True
        for cs in chips:
            if cs not in h.ref_sg:
                if not await h.capture_reference(cs):
                    latch_ok = False
            if cs not in h.ref_sg:
                print("  -> chip is not answering stably at the known-good"
                      " settings; nothing below would mean anything. Stopping.")
                return 1
        print()
        h.se_tracks_cs = await probe_se_support(h, chips)

        print("\n=== settle x clock sweep (chopper off throughout) ===")
        print(f"{'cs':>3} {'settle':>8} {'clock':>9} {'result':>8} "
              f"{'ms/10frames':>12}  detail")
        best: dict[int, tuple[int, int, float]] = {}
        for cs in chips:
            for settle_us in SETTLES_US:
                for clock_hz in CLOCKS_HZ:
                    ok, per10, detail = await grid_point(
                        h, cs, settle_us, clock_hz, args.trials)
                    print(f"{cs:>3} {settle_us:>6}us {clock_hz//1000:>6}kHz "
                          f"{'PASS' if ok else 'FAIL':>8} {per10:>11.2f}  {detail}")
                    if ok and (cs not in best or per10 < best[cs][2]):
                        best[cs] = (settle_us, clock_hz, per10)

        print("\n=== repetition count: is x5 doing anything x1 does not? ===")
        if not latch_ok:
            print("  skipped: RDSEL=00 and RDSEL=01 are indistinguishable here")
        else:
            for cs in chips:
                for label, se_us, ck in (("known-good", SAFE_SETTLE_S * 1e6,
                                          SAFE_CLOCK_HZ),
                                         ("proposed", 100, 500_000)):
                    sb._CS_SETTLE_S = se_us / 1e6
                    be._spi.max_speed_hz = ck
                    for cycles in (5, 2, 1):
                        ok, detail = await cycles_point(h, cs, cycles,
                                                        args.trials)
                        print(f"  cs={cs} {label:>10} {int(se_us):>3}us/"
                              f"{ck//1000}kHz cycles={cycles} "
                              f"{'PASS' if ok else 'FAIL':>6}  {detail}")
                await h.recover(cs)

        print("\n=== fastest framing that passed ===")
        for cs in chips:
            if cs in best:
                se, ck, per10 = best[cs]
                print(f"  cs={cs}: settle={se}us clock={ck//1000}kHz "
                      f"-> {per10:.2f} ms per 10 frames "
                      f"(baseline ~21.8 ms)")
            else:
                print(f"  cs={cs}: nothing faster than baseline passed")
        print("\nPick the SLOWEST setting that passed on ALL chips, then add"
              " margin — cs=1 (BEND, SAI5_RXD1) is the pad the 500 us was"
              " chosen for and is expected to be the limiting one.")
        return 0
    finally:
        # Always leave the bench in the state the server expects to find.
        sb._CS_SETTLE_S = SAFE_SETTLE_S
        try:
            be._spi.max_speed_hz = SAFE_CLOCK_HZ
        except Exception:
            pass
        for cs in chips:
            try:
                await h.silence(cs, cycles=5)
            except Exception:
                pass
        try:
            await be.close()
        except Exception:
            pass
        print("\nrestored: 500us / 50kHz, all chips silenced (TOFF=0, CS=0)")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
