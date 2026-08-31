"""
test_state_persistence_offloop.py — persisting positions must not block
the event loop, and must not race the motion coroutine that feeds it.

Every jog and every move ends by writing /var/lib/ortho-bender's state
file. On the board's eMMC that write measured 0.87 ms typical and 1.6 ms
worst, and it was happening ON the event loop — so it was added not only
to the move that triggered it but to every concurrent request, which on a
bench whose HTTP floor is 7 ms is a visible share of the jitter.

Moving it to a worker thread introduces the failure this file guards:
json.dump iterating self.positions while the motion coroutine is still
crediting steps into it raises "dictionary changed size during iteration",
and it would do so rarely and only under load. The snapshot must therefore
be taken on the loop and only the copy handed to the thread.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import json

import pytest

from server.services import spi_backend as sb
from server.services.spi_backend import SpidevMotorBackend


class _Backend(SpidevMotorBackend):
    """Records writes instead of touching the filesystem."""

    def __init__(self):
        super().__init__()
        self.writes: list[dict] = []
        self.write_hook = None

    def _write_state(self, data):
        if self.write_hook is not None:
            self.write_hook()
        self.writes.append(data)


def test_snapshot_is_taken_on_the_loop_not_in_the_thread():
    """The thread must receive a COPY. If it received the live dicts, a
    move crediting steps mid-write would raise mid-iteration."""
    be = _Backend()
    be.positions[0] = 1
    snap = be._state_snapshot()
    be.positions[0] = 2
    be.positions[99] = 7                      # a new key: the racy case
    assert snap["positions"]["0"] == 1, "snapshot did not capture the value"
    assert "99" not in snap["positions"], "snapshot aliases the live dict"
    assert snap["positions"]["0"] != be.positions[0], "snapshot moved with it"


def test_deferred_save_writes_the_state():
    be = _Backend()

    async def go():
        be.positions[1] = 964
        be._save_state_soon()
        await asyncio.sleep(0)
        for _ in range(50):                   # let the worker finish
            if be.writes:
                break
            await asyncio.sleep(0.01)
        if be._state_save_task:
            await be._state_save_task

    asyncio.run(go())
    assert be.writes, "deferred save never wrote"
    assert be.writes[-1]["positions"]["1"] == 964


def test_a_burst_of_moves_coalesces_into_fewer_writes():
    """Ten jogs in flight must not queue ten eMMC writes; the last state
    is what matters, and the file has to end up holding it.

    The coalescing comes from the _state_dirty flag, not from the
    in-flight task check — removing that check is a semantically
    equivalent mutation and this test correctly does not flag it.
    """
    be = _Backend()

    async def go():
        for i in range(10):
            be.positions[1] = i
            be._save_state_soon()
        if be._state_save_task:
            await be._state_save_task

    asyncio.run(go())
    assert 0 < len(be.writes) < 10, f"{len(be.writes)} writes for 10 moves"
    assert be.writes[-1]["positions"]["1"] == 9, "final state not persisted"


def test_position_mutation_during_the_write_does_not_raise():
    """The regression this file exists for: the motion coroutine keeps
    crediting steps while the write is in flight."""
    be = _Backend()

    def mutate_mid_write():
        be.positions[3] = be.positions.get(3, 0) + 1
        be.positions[100 + len(be.writes)] = 1     # grow the dict

    be.write_hook = mutate_mid_write

    async def go():
        for _ in range(20):
            be._save_state_soon()
            await asyncio.sleep(0)
        if be._state_save_task:
            await be._state_save_task

    asyncio.run(go())          # must not raise RuntimeError from json.dump
    assert be.writes


def test_sync_save_still_works_without_a_running_loop():
    """close() and startup persist synchronously; there is no loop then."""
    be = _Backend()
    be.positions[0] = 5
    be._save_state_soon()      # no running loop -> falls back to sync
    assert be.writes, "no synchronous fallback outside the event loop"
    assert be.writes[-1]["positions"]["0"] == 5


def test_real_write_round_trips_through_the_file(tmp_path, monkeypatch):
    """The snapshot must still be the shape _load_state() expects — the
    refactor split one function into three and the file format is the
    contract between them."""
    path = tmp_path / "motion_state.json"
    monkeypatch.setattr(sb, "_STATE_FILE", str(path))
    be = SpidevMotorBackend()
    be.positions[1] = 964
    be.homed_persist = {1, 3}
    be.run_cs_map = {1: 14}
    be.hold_cs_map = {3: 8}
    be.sgt_map = {1: 8}
    be._save_state()

    on_disk = json.loads(path.read_text())
    assert on_disk["positions"]["1"] == 964
    assert on_disk["hold_cs"]["3"] == 8

    fresh = SpidevMotorBackend()
    fresh._load_state()
    assert fresh.positions[1] == 964
    assert fresh.homed_persist == {1, 3}
    assert fresh.run_cs_map == {1: 14}
    assert fresh.hold_cs_map == {3: 8}
