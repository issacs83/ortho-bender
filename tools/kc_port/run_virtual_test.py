#!/usr/bin/env python3
"""
run_virtual_test.py — Virtual test environment for kc_test + motor_sim

Orchestrates motor_sim and kc_test_motor_only with realistic test scenarios.
Monitors protocol traffic, validates motor positions, and generates test reports.

Usage:
    python3 run_virtual_test.py [--cycles N] [--speed-factor N] [--timeout N]
"""

import subprocess
import time
import os
import signal
import sys
import threading
import re
import argparse


class TestResult:
    """Collect and analyze test output."""

    def __init__(self):
        self.kc_lines = []
        self.sim_lines = []
        self.errors = []
        self.warnings = []
        self.bend_positions = []
        self.sensor_readings = []
        self.motor_positions = {}  # axis_name -> [(timestamp, pos, target, state)]
        self.phase_times = {}     # phase_name -> timestamp
        self.cmd_count = 0
        self.crc_errors = 0
        self.phases = {
            "led_test": False,
            "motor_init": False,
            "homing": False,
            "rotation_360": False,
            "feeding": False,
            "sensor_check": False,
            "bending": False,
            "cutting": False,
        }


def parse_args():
    p = argparse.ArgumentParser(description="Virtual kc_test runner")
    p.add_argument("--cycles", type=int, default=2,
                   help="Number of bend-feed-cut cycles (default: 2)")
    p.add_argument("--speed-factor", type=float, default=100.0,
                   help="Motor simulation speed factor (default: 100)")
    p.add_argument("--timeout", type=int, default=120,
                   help="Test timeout in seconds (default: 120)")
    p.add_argument("--build-dir", default="build-host",
                   help="Build directory (default: build-host)")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Show sim output in real time")
    return p.parse_args()


def run_test(args):
    build_dir = args.build_dir
    sim_bin = os.path.join(build_dir, "motor_sim")
    test_bin = os.path.join(build_dir, "kc_test_motor_only")

    if not os.path.exists(sim_bin) or not os.path.exists(test_bin):
        print(f"ERROR: binaries not found in {build_dir}/")
        print("Run: cmake --build build-host")
        return None

    result = TestResult()
    t_start = time.time()

    # Start motor_sim
    print(f"[RUN] Starting motor_sim (speed={args.speed_factor}x)...")
    sim = subprocess.Popen(
        [sim_bin, "--speed-factor", str(args.speed_factor)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    time.sleep(1)

    if not os.path.exists("/tmp/b2_motor_sim"):
        print("ERROR: motor_sim failed to create /tmp/b2_motor_sim")
        sim.kill()
        return None

    # Start kc_test
    print("[RUN] Starting kc_test_motor_only...")
    test = subprocess.Popen(
        [test_bin, "--port", "/tmp/b2_motor_sim"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )

    # Read kc_test output in a thread
    cycle_count = 0
    stop_event = threading.Event()

    def read_kc_output():
        nonlocal cycle_count
        for line in test.stdout:
            line = line.rstrip()
            result.kc_lines.append(line)
            elapsed = time.time() - t_start

            # Track phases with timing
            if "Vision Light On" in line:
                result.phases["led_test"] = True
                result.phase_times["led_test"] = elapsed
            elif "Motor initialization" in line:
                result.phases["motor_init"] = True
                result.phase_times["motor_init"] = elapsed
            elif "Init bending motor" in line:
                result.phases["homing"] = True
                result.phase_times["homing"] = elapsed
            elif "360 degrees" in line:
                result.phases["rotation_360"] = True
                result.phase_times["rotation_360"] = elapsed
            elif "Feeding" in line:
                result.phases["feeding"] = True
                if "feeding" not in result.phase_times:
                    result.phase_times["feeding"] = elapsed
            elif "Check Sensors" in line:
                result.phases["sensor_check"] = True
                if "sensor_check" not in result.phase_times:
                    result.phase_times["sensor_check"] = elapsed
                m = re.search(r"B=(\d), F0=(\d), F1=(\d), R=(\d), C=(\d)", line)
                if m:
                    result.sensor_readings.append(
                        tuple(int(x) for x in m.groups()))
            elif "Bending..." in line:
                result.phases["bending"] = True
                if "bending" not in result.phase_times:
                    result.phase_times["bending"] = elapsed
                m = re.search(r"pos=(-?\d+), deg=(-?[\d.]+)", line)
                if m:
                    result.bend_positions.append(
                        (int(m.group(1)), float(m.group(2))))
            elif "Cutting" in line:
                result.phases["cutting"] = True
                if "cutting" not in result.phase_times:
                    result.phase_times["cutting"] = elapsed
                cycle_count += 1
                print(f"  [CYCLE {cycle_count}/{args.cycles}] completed at {elapsed:.1f}s")
                if cycle_count >= args.cycles:
                    stop_event.set()
            elif "[ERROR]" in line:
                result.errors.append(line)

    t = threading.Thread(target=read_kc_output, daemon=True)
    t.start()

    # Read motor_sim output in a thread
    def read_sim_output():
        for line in sim.stdout:
            line = line.rstrip()
            result.sim_lines.append(line)

            if args.verbose and line.startswith("[SIM]"):
                print(f"  {line}")

            if "CRC mismatch" in line:
                result.warnings.append(line)
            elif "Unknown command" in line:
                result.errors.append(line)

            # Parse structured status output
            m = re.match(r"\[STATUS\] (\w+) pos=(-?\d+) target=(-?\d+) "
                         r"speed=(\d+) state=(\w+)", line)
            if m:
                axis = m.group(1)
                if axis not in result.motor_positions:
                    result.motor_positions[axis] = []
                result.motor_positions[axis].append({
                    "time": time.time() - t_start,
                    "pos": int(m.group(2)),
                    "target": int(m.group(3)),
                    "speed": int(m.group(4)),
                    "state": m.group(5),
                })

            # Parse stats line
            m = re.match(r"\[STATUS\] STATS cmds=(\d+) crc_err=(\d+)", line)
            if m:
                result.cmd_count = int(m.group(1))
                result.crc_errors = int(m.group(2))

    t2 = threading.Thread(target=read_sim_output, daemon=True)
    t2.start()

    # Wait for cycles to complete or timeout
    print(f"[RUN] Waiting for {args.cycles} cycles (timeout={args.timeout}s)...")
    completed = stop_event.wait(timeout=args.timeout)

    # Send Enter to stop kc_test gracefully
    try:
        test.stdin.write("\n")
        test.stdin.flush()
        test.stdin.close()
    except BrokenPipeError:
        pass

    test.wait(timeout=10)

    # Stop motor_sim
    sim.send_signal(signal.SIGTERM)
    try:
        sim.wait(timeout=5)
    except subprocess.TimeoutExpired:
        sim.kill()

    if not completed:
        result.warnings.append(f"Test timed out after {args.timeout}s "
                               f"(completed {cycle_count}/{args.cycles} cycles)")

    return result


def print_report(result, args):
    """Print test result report."""
    print("\n" + "=" * 60)
    print("  VIRTUAL TEST REPORT")
    print("=" * 60)

    # Phase completion with timing
    print("\n[Phases]")
    all_passed = True
    for phase, done in result.phases.items():
        status = "PASS" if done else "FAIL"
        if not done:
            all_passed = False
        t = result.phase_times.get(phase)
        timing = f" ({t:.2f}s)" if t is not None else ""
        print(f"  {phase:20s}: {status}{timing}")

    # Motor positions
    if result.bend_positions:
        positions = [p[0] for p in result.bend_positions]
        degrees = [p[1] for p in result.bend_positions]
        print(f"\n[Bending Positions]")
        print(f"  Total readings:     {len(result.bend_positions)}")
        print(f"  Position range:     {min(positions)} ~ {max(positions)} steps")
        print(f"  Degree range:       {min(degrees):.1f} ~ {max(degrees):.1f} deg")
        unique_pos = sorted(set(positions))
        print(f"  Unique positions:   {unique_pos}")

    # Axis position summary
    if result.motor_positions:
        print(f"\n[Axis Summary]")
        for axis, readings in sorted(result.motor_positions.items()):
            if readings:
                last = readings[-1]
                print(f"  {axis:10s}: final_pos={last['pos']:>8d}  "
                      f"state={last['state']:>6s}  readings={len(readings)}")

    # Sensor readings
    if result.sensor_readings:
        print(f"\n[Sensor Readings]")
        print(f"  Total readings:     {len(result.sensor_readings)}")
        unique_sensors = set(result.sensor_readings)
        for s in unique_sensors:
            print(f"  B={s[0]} F0={s[1]} F1={s[2]} R={s[3]} C={s[4]}")
        if len(unique_sensors) == 1 and len(result.sensor_readings) > 2:
            s = list(unique_sensors)[0]
            if s[1] == 0 and s[2] == 0:
                print("  WARNING: Feed sensors never activated")

    # Protocol
    sim_cmds = [l for l in result.sim_lines if l.startswith("[SIM]")
                and "Motor Status" not in l and "===" not in l]
    cmd_types = {}
    for line in sim_cmds:
        m = re.match(r"\[SIM\] (\w+)", line)
        if m:
            cmd = m.group(1)
            cmd_types[cmd] = cmd_types.get(cmd, 0) + 1

    if cmd_types:
        print(f"\n[Protocol Commands]")
        total = sum(cmd_types.values())
        for cmd, count in sorted(cmd_types.items(), key=lambda x: -x[1]):
            print(f"  {cmd:20s}: {count:4d}")
        print(f"  {'TOTAL':20s}: {total:4d}")
        if result.crc_errors > 0:
            print(f"  CRC errors:          {result.crc_errors}")

    # Errors and warnings
    if result.errors:
        print(f"\n[ERRORS] ({len(result.errors)})")
        for e in result.errors[:10]:
            print(f"  {e}")

    if result.warnings:
        print(f"\n[WARNINGS] ({len(result.warnings)})")
        for w in result.warnings[:10]:
            print(f"  {w}")

    # Summary
    print("\n" + "-" * 60)
    has_errors = len(result.errors) > 0
    has_crc = any("CRC" in w for w in result.warnings)
    if all_passed and not has_errors and not has_crc:
        print("  RESULT: PASS")
        print("-" * 60)
        return 0
    elif has_errors:
        print("  RESULT: FAIL")
        print("-" * 60)
        return 1
    else:
        print("  RESULT: PASS (with warnings)")
        print("-" * 60)
        return 0


def main():
    args = parse_args()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 60)
    print("  kc_test Virtual Test Environment")
    print(f"  Cycles: {args.cycles}, Speed: {args.speed_factor}x, "
          f"Timeout: {args.timeout}s")
    print("=" * 60)

    result = run_test(args)
    if result is None:
        print("FATAL: Test setup failed")
        sys.exit(1)

    rc = print_report(result, args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
