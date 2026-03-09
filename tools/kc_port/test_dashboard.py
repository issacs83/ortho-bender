#!/usr/bin/env python3
"""
test_dashboard.py — Web dashboard for kc_test virtual test environment

Three-panel layout with real-time monitoring:
  Left:   Controls + Test Phases
  Center: Motion visualization + Log viewer
  Right:  Axis details + Sensors + Protocol statistics

Usage:
    python3 test_dashboard.py [--port 8080] [--build-dir build-host]
"""

import http.server
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import argparse
from urllib.parse import urlparse, parse_qs

# ── Globals ──

g_build_dir = "build-host"
g_test_proc = None
g_test_lock = threading.Lock()
g_event_queues = []
g_event_lock = threading.Lock()


def broadcast_event(event_type, data):
    """Send SSE event to all connected clients."""
    msg = json.dumps(data)
    with g_event_lock:
        dead = []
        for q in g_event_queues:
            try:
                q.put_nowait((event_type, msg))
            except queue.Full:
                dead.append(q)
        for q in dead:
            g_event_queues.remove(q)


class TestRunner:
    """Manages motor_sim + kc_test processes."""

    def __init__(self, build_dir, speed_factor=100.0, cycles=3, timeout=120):
        self.build_dir = build_dir
        self.speed_factor = speed_factor
        self.cycles = cycles
        self.timeout = timeout
        self.sim_proc = None
        self.test_proc = None
        self.running = False
        self.phases = {
            "led_test": False, "motor_init": False, "homing": False,
            "rotation_360": False, "feeding": False, "sensor_check": False,
            "bending": False, "cutting": False,
        }
        self.sensors = {"B": 0, "F0": 0, "F1": 0, "R": 0, "C": 0}
        self.axes = {
            "BENDER": {"pos": 0, "target": 0, "speed": 0, "state": "IDLE"},
            "FEEDER": {"pos": 0, "target": 0, "speed": 0, "state": "IDLE"},
            "CUTTER": {"pos": 0, "target": 0, "speed": 0, "state": "IDLE"},
        }
        self.bend_positions = []
        self.cycle_count = 0
        self.errors = []
        self.protocol_stats = {}
        self.cmd_total = 0
        self.crc_errors = 0
        self.start_time = 0

    def start(self):
        self.running = True
        self.start_time = time.time()
        self.phases = {k: False for k in self.phases}
        self.sensors = {"B": 0, "F0": 0, "F1": 0, "R": 0, "C": 0}
        self.axes = {k: {"pos": 0, "target": 0, "speed": 0, "state": "IDLE"}
                     for k in self.axes}
        self.bend_positions = []
        self.cycle_count = 0
        self.errors = []
        self.protocol_stats = {}
        self.cmd_total = 0
        self.crc_errors = 0

        sim_bin = os.path.join(self.build_dir, "motor_sim")
        test_bin = os.path.join(self.build_dir, "kc_test_motor_only")

        if not os.path.exists(sim_bin) or not os.path.exists(test_bin):
            broadcast_event("error", {"message": f"Binaries not found in {self.build_dir}/"})
            self.running = False
            return False

        broadcast_event("status", {"state": "starting", "message": "Starting motor_sim..."})

        self.sim_proc = subprocess.Popen(
            [sim_bin, "--speed-factor", str(self.speed_factor)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        time.sleep(1)

        if not os.path.exists("/tmp/b2_motor_sim"):
            broadcast_event("error", {"message": "motor_sim failed to create PTY"})
            self.sim_proc.kill()
            self.running = False
            return False

        broadcast_event("status", {"state": "starting", "message": "Starting kc_test..."})

        self.test_proc = subprocess.Popen(
            [test_bin, "--port", "/tmp/b2_motor_sim"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )

        threading.Thread(target=self._read_kc_output, daemon=True).start()
        threading.Thread(target=self._read_sim_output, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()

        broadcast_event("status", {"state": "running", "message": "Test running..."})
        return True

    def stop(self):
        if not self.running:
            return
        self.running = False

        if self.test_proc and self.test_proc.poll() is None:
            try:
                self.test_proc.stdin.write("\n")
                self.test_proc.stdin.flush()
                self.test_proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                self.test_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.test_proc.kill()

        if self.sim_proc and self.sim_proc.poll() is None:
            self.sim_proc.send_signal(signal.SIGTERM)
            try:
                self.sim_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.sim_proc.kill()

        elapsed = time.time() - self.start_time
        all_pass = all(self.phases.values())
        has_errors = len(self.errors) > 0

        result_str = "PASS" if (all_pass and not has_errors) else "FAIL"
        broadcast_event("status", {
            "state": "completed",
            "message": f"Test {result_str} ({elapsed:.1f}s, {self.cycle_count} cycles)"
        })
        broadcast_event("result", {
            "result": result_str,
            "elapsed": round(elapsed, 1),
            "cycles": self.cycle_count,
            "phases": self.phases,
            "errors": self.errors[:20],
            "protocol_stats": self.protocol_stats,
            "cmd_total": self.cmd_total,
            "crc_errors": self.crc_errors,
            "axes": self.axes,
            "bend_count": len(self.bend_positions),
        })

    def _read_kc_output(self):
        try:
            for line in self.test_proc.stdout:
                if not self.running:
                    break
                line = line.rstrip()
                broadcast_event("kc_log", {"line": line})
                self._parse_kc_line(line)
        except (ValueError, OSError):
            pass

    def _parse_kc_line(self, line):
        if "Vision Light On" in line:
            self.phases["led_test"] = True
        elif "Motor initialization" in line:
            self.phases["motor_init"] = True
        elif "Init bending motor" in line:
            self.phases["homing"] = True
        elif "360 degrees" in line:
            self.phases["rotation_360"] = True
        elif "Feeding" in line:
            self.phases["feeding"] = True
        elif "Check Sensors" in line:
            self.phases["sensor_check"] = True
            m = re.search(r"B=(\d), F0=(\d), F1=(\d), R=(\d), C=(\d)", line)
            if m:
                self.sensors = {
                    "B": int(m.group(1)), "F0": int(m.group(2)),
                    "F1": int(m.group(3)), "R": int(m.group(4)),
                    "C": int(m.group(5))
                }
                broadcast_event("sensors", self.sensors)
        elif "Bending..." in line:
            self.phases["bending"] = True
            m = re.search(r"pos=(-?\d+), deg=(-?[\d.]+)", line)
            if m:
                pos = int(m.group(1))
                deg = float(m.group(2))
                self.bend_positions.append({"pos": pos, "deg": deg})
                broadcast_event("bend", {"pos": pos, "deg": deg,
                                         "count": len(self.bend_positions)})
        elif "Cutting" in line:
            self.phases["cutting"] = True
            self.cycle_count += 1
            broadcast_event("cycle", {"count": self.cycle_count,
                                      "target": self.cycles})
            if self.cycle_count >= self.cycles:
                threading.Thread(target=self.stop, daemon=True).start()
        elif "[ERROR]" in line:
            self.errors.append(line)
            broadcast_event("error", {"message": line})

        broadcast_event("phases", self.phases)

    def _read_sim_output(self):
        try:
            for line in self.sim_proc.stdout:
                if not self.running:
                    break
                line = line.rstrip()

                # Parse structured status for axis positions
                m = re.match(r"\[STATUS\] (\w+) pos=(-?\d+) target=(-?\d+) "
                             r"speed=(\d+) state=(\w+)", line)
                if m:
                    axis = m.group(1)
                    if axis in self.axes:
                        self.axes[axis] = {
                            "pos": int(m.group(2)),
                            "target": int(m.group(3)),
                            "speed": int(m.group(4)),
                            "state": m.group(5),
                        }
                        broadcast_event("axis", {"name": axis, **self.axes[axis]})
                    continue

                # Parse sensor status from sim
                m = re.match(r"\[STATUS\] SENSORS B=(\d) F0=(\d) F1=(\d) "
                             r"R=(\d) C=(\d)", line)
                if m:
                    continue  # tracked via kc_test output

                # Parse command stats
                m = re.match(r"\[STATUS\] STATS cmds=(\d+) crc_err=(\d+)", line)
                if m:
                    self.cmd_total = int(m.group(1))
                    self.crc_errors = int(m.group(2))
                    broadcast_event("stats", {
                        "cmd_total": self.cmd_total,
                        "crc_errors": self.crc_errors,
                        "protocol": self.protocol_stats,
                    })
                    continue

                if not line.startswith("[SIM]"):
                    continue
                if "Motor Status" in line or "===" in line:
                    continue

                m = re.match(r"\[SIM\] (\w+)", line)
                if m:
                    cmd = m.group(1)
                    self.protocol_stats[cmd] = self.protocol_stats.get(cmd, 0) + 1

                # Forward motor commands to dashboard
                if any(x in line for x in ["BENDER", "FEEDER", "CUTTER",
                                           "INIT", "MOVEVEL", "MOVEABS"]):
                    broadcast_event("sim_log", {"line": line})
        except (ValueError, OSError):
            pass

    def _watchdog(self):
        deadline = time.time() + self.timeout
        while self.running and time.time() < deadline:
            time.sleep(1)
            elapsed = time.time() - self.start_time
            broadcast_event("tick", {
                "elapsed": round(elapsed, 1),
                "cycles": self.cycle_count,
                "target": self.cycles,
            })
        if self.running:
            broadcast_event("error", {"message": f"Timeout after {self.timeout}s"})
            self.stop()


# ── Dashboard HTML ──

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KC Test Dashboard — Ortho-Bender</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0d1117;--bg2:#161b22;--border:#30363d;--text:#c9d1d9;--dim:#8b949e;
--blue:#58a6ff;--green:#3fb950;--red:#f85149;--purple:#d2a8ff;--cyan:#79c0ff;--orange:#d29922}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,monospace;
background:var(--bg);color:var(--text);display:flex;flex-direction:column;height:100vh}

/* ── Top Status Bar ── */
.topbar{background:var(--bg2);border-bottom:1px solid var(--border);
padding:10px 20px;display:flex;align-items:center;gap:16px}
.topbar h1{font-size:16px;color:var(--blue);font-weight:600;white-space:nowrap}
.topbar .sub{font-size:11px;color:var(--dim)}
.badge{padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700}
.badge-idle{background:#30363d;color:var(--dim)}
.badge-running{background:#1f6feb33;color:var(--blue);animation:pulse 1.5s infinite}
.badge-pass{background:#23863533;color:var(--green)}
.badge-fail{background:#f8514933;color:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}
.timer{margin-left:auto;font-size:14px;color:var(--dim);font-variant-numeric:tabular-nums}
.cycle-bar{display:flex;gap:4px;align-items:center}
.cycle-dot{width:10px;height:10px;border-radius:50%;background:var(--border);transition:.2s}
.cycle-dot.done{background:var(--green);box-shadow:0 0 6px #3fb95066}

/* ── Controls ── */
.controls{padding:8px 20px;background:var(--bg2);border-bottom:1px solid var(--border);
display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.ctrl-group{display:flex;align-items:center;gap:4px}
.ctrl-group label{font-size:11px;color:var(--dim);min-width:50px}
.ctrl-group input{width:70px;padding:3px 6px;border:1px solid var(--border);
background:var(--bg);color:var(--text);border-radius:4px;font-size:12px}
.btn{padding:5px 14px;border:1px solid var(--border);border-radius:6px;
font-size:12px;cursor:pointer;font-weight:600;transition:.15s}
.btn-start{background:#238636;color:#fff;border-color:#238636}
.btn-start:hover{background:#2ea043}
.btn-start:disabled{background:var(--border);color:#484f58;cursor:not-allowed}
.btn-stop{background:#da3633;color:#fff;border-color:#da3633}
.btn-stop:hover{background:var(--red)}

/* ── Three Column Layout ── */
.main{display:flex;flex:1;overflow:hidden}

/* Left Panel */
.panel-left{width:220px;min-width:220px;background:var(--bg2);
border-right:1px solid var(--border);overflow-y:auto;padding:10px}

/* Center Panel */
.panel-center{flex:1;display:flex;flex-direction:column;overflow:hidden}

/* Right Panel */
.panel-right{width:260px;min-width:260px;background:var(--bg2);
border-left:1px solid var(--border);overflow-y:auto;padding:10px}

/* ── Sections ── */
.section{margin-bottom:14px}
.section-title{font-size:10px;text-transform:uppercase;letter-spacing:1px;
color:var(--dim);margin-bottom:6px;font-weight:700}

/* Phases */
.phase-item{display:flex;align-items:center;gap:6px;padding:2px 6px;font-size:12px}
.phase-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.phase-dot.off{background:var(--border)}
.phase-dot.on{background:var(--green);box-shadow:0 0 6px #3fb95066}
.phase-dot.active{background:var(--blue);animation:pulse 1s infinite}

/* Sensors */
.sensor-row{display:grid;grid-template-columns:repeat(5,1fr);gap:4px}
.sensor-cell{text-align:center;padding:6px 2px;border-radius:4px;
background:var(--bg);border:1px solid var(--border)}
.sensor-cell .lbl{font-size:9px;color:var(--dim)}
.sensor-cell .val{font-size:16px;font-weight:700;margin-top:1px}
.sensor-on{color:var(--green)}
.sensor-off{color:#484f58}

/* Axis Detail */
.axis-card{background:var(--bg);border:1px solid var(--border);border-radius:6px;
padding:8px;margin-bottom:6px}
.axis-card .name{font-size:11px;font-weight:700;color:var(--blue);margin-bottom:4px;
display:flex;justify-content:space-between}
.axis-card .name .state{font-size:10px;padding:1px 6px;border-radius:8px}
.state-idle{background:var(--border);color:var(--dim)}
.state-moving{background:#1f6feb33;color:var(--blue);animation:pulse 1s infinite}
.axis-row{display:flex;justify-content:space-between;font-size:11px;padding:1px 0}
.axis-row .k{color:var(--dim)}
.axis-row .v{color:var(--text);font-variant-numeric:tabular-nums}

/* Protocol Stats */
.proto-row{display:flex;justify-content:space-between;font-size:11px;padding:1px 4px}
.proto-row .cmd{color:var(--dim)}.proto-row .cnt{color:var(--cyan);font-weight:600}
.proto-total{border-top:1px solid var(--border);margin-top:4px;padding-top:4px;
font-size:11px;font-weight:700}

/* Stats Summary */
.stat-row{display:flex;justify-content:space-between;font-size:12px;padding:2px 4px}
.stat-row .k{color:var(--dim)}.stat-row .v{color:var(--blue);font-weight:600}

/* ── Center: Motion Viz + Log ── */
.motion-panel{display:flex;gap:8px;padding:10px 12px;background:var(--bg2);
border-bottom:1px solid var(--border);flex-shrink:0;align-items:flex-start}
.dial-container{text-align:center}
.dial-title{font-size:10px;text-transform:uppercase;letter-spacing:1px;
color:var(--dim);margin-bottom:4px;font-weight:700}
.dial-info{font-size:10px;color:var(--dim);margin-top:2px;font-variant-numeric:tabular-nums}
.trend-container{flex:1;min-width:0;display:flex;flex-direction:column}
.trend-chart{height:140px;background:var(--bg);border:1px solid var(--border);
border-radius:6px;position:relative;overflow:hidden}
.trend-chart canvas{width:100%;height:100%}
.trend-legend{display:flex;gap:12px;justify-content:center;margin-top:4px}
.trend-legend span{font-size:9px;display:flex;align-items:center;gap:3px}
.trend-legend .dot{width:8px;height:2px;display:inline-block;border-radius:1px}

.log-tabs{padding:6px 12px;background:var(--bg2);border-bottom:1px solid var(--border);
display:flex;gap:6px}
.log-tab{padding:3px 10px;border-radius:4px;font-size:11px;
cursor:pointer;color:var(--dim);border:none;background:transparent}
.log-tab.active{background:var(--border);color:var(--text)}
.log-area{flex:1;overflow-y:auto;padding:6px 12px;font-family:'JetBrains Mono','Fira Code',monospace;
font-size:11px;line-height:1.5}
.log-line{white-space:pre-wrap;word-break:break-all}
.log-line.error{color:var(--red)}.log-line.phase{color:var(--green)}
.log-line.sensor{color:var(--purple)}.log-line.bend{color:var(--cyan)}
.log-line.sim{color:var(--dim)}

/* ── Result Overlay ── */
.overlay{position:fixed;inset:0;background:#0d1117cc;display:none;
align-items:center;justify-content:center;z-index:100}
.overlay.show{display:flex}
.result-card{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
padding:28px;min-width:420px;max-width:620px;max-height:80vh;overflow-y:auto}
.result-card h2{font-size:22px;margin-bottom:12px}
.result-card .pass{color:var(--green)}.result-card .fail{color:var(--red)}
.result-card table{width:100%;border-collapse:collapse;margin:8px 0}
.result-card td{padding:3px 6px;font-size:12px;border-bottom:1px solid #21262d}
.result-card td:first-child{color:var(--dim)}
.close-btn{margin-top:14px;width:100%;padding:7px;background:var(--border);
border:none;color:var(--text);border-radius:6px;cursor:pointer;font-size:13px}
</style>
</head>
<body>

<!-- Top Status Bar -->
<div class="topbar">
    <h1>KC Test Dashboard</h1>
    <span class="sub">Ortho-Bender Virtual Motor Controller</span>
    <span id="statusBadge" class="badge badge-idle">IDLE</span>
    <div class="cycle-bar" id="cycleBar"></div>
    <span class="timer" id="timerDisplay">00:00</span>
</div>

<!-- Controls -->
<div class="controls">
    <div class="ctrl-group"><label>Cycles</label>
        <input type="number" id="inCycles" value="3" min="1" max="50"></div>
    <div class="ctrl-group"><label>Speed</label>
        <input type="number" id="inSpeed" value="100" min="1" max="1000"></div>
    <div class="ctrl-group"><label>Timeout</label>
        <input type="number" id="inTimeout" value="120" min="10" max="600"></div>
    <button class="btn btn-start" id="btnStart" onclick="startTest()">Start Test</button>
    <button class="btn btn-stop" id="btnStop" onclick="stopTest()" style="display:none">Stop</button>
</div>

<!-- Three Column Layout -->
<div class="main">
    <!-- Left: Phases + Stats -->
    <div class="panel-left">
        <div class="section">
            <div class="section-title">Test Phases</div>
            <div id="phaseGrid"></div>
        </div>
        <div class="section">
            <div class="section-title">Statistics</div>
            <div class="stat-row"><span class="k">Cycles</span><span class="v" id="stCycles">0 / 0</span></div>
            <div class="stat-row"><span class="k">Bends</span><span class="v" id="stBends">0</span></div>
            <div class="stat-row"><span class="k">Commands</span><span class="v" id="stCmds">0</span></div>
            <div class="stat-row"><span class="k">CRC Errors</span><span class="v" id="stCRC">0</span></div>
            <div class="stat-row"><span class="k">Errors</span><span class="v" id="stErrors">0</span></div>
        </div>
        <div class="section">
            <div class="section-title">Bend Position</div>
            <div id="bendInfo" style="font-size:11px;color:var(--cyan);padding:2px 4px">—</div>
        </div>
    </div>

    <!-- Center: Motion + Logs -->
    <div class="panel-center">
        <!-- Motion Visualization -->
        <div class="motion-panel">
            <div class="dial-container">
                <div class="dial-title">Bend Axis</div>
                <svg id="bendDial" width="200" height="200" viewBox="0 0 200 200"></svg>
                <div class="dial-info" id="bendDialInfo">0 steps / 0.0°</div>
            </div>
            <div class="dial-container">
                <div class="dial-title">Rotate Axis</div>
                <svg id="rotateDial" width="140" height="140" viewBox="0 0 140 140"></svg>
                <div class="dial-info" id="rotateDialInfo">—</div>
            </div>
            <div class="trend-container">
                <div class="dial-title">Bend Position Trend</div>
                <div class="trend-chart"><canvas id="trendCanvas"></canvas></div>
                <div class="trend-legend">
                    <span><span class="dot" style="background:#58a6ff"></span> Actual</span>
                    <span><span class="dot" style="background:#d29922"></span> Target</span>
                </div>
            </div>
        </div>
        <!-- Log Viewer -->
        <div class="log-tabs">
            <button class="log-tab active" onclick="switchTab('all',this)">All</button>
            <button class="log-tab" onclick="switchTab('kc',this)">KC Test</button>
            <button class="log-tab" onclick="switchTab('sim',this)">Simulator</button>
        </div>
        <div class="log-area" id="logArea"></div>
    </div>

    <!-- Right: Axes + Sensors + Protocol -->
    <div class="panel-right">
        <div class="section">
            <div class="section-title">Motor Axes</div>
            <div id="axisCards"></div>
        </div>
        <div class="section">
            <div class="section-title">Sensors</div>
            <div class="sensor-row">
                <div class="sensor-cell"><div class="lbl">B</div><div class="val sensor-off" id="sB">—</div></div>
                <div class="sensor-cell"><div class="lbl">F0</div><div class="val sensor-off" id="sF0">—</div></div>
                <div class="sensor-cell"><div class="lbl">F1</div><div class="val sensor-off" id="sF1">—</div></div>
                <div class="sensor-cell"><div class="lbl">R</div><div class="val sensor-off" id="sR">—</div></div>
                <div class="sensor-cell"><div class="lbl">C</div><div class="val sensor-off" id="sC">—</div></div>
            </div>
        </div>
        <div class="section">
            <div class="section-title">Protocol Commands</div>
            <div id="protoList"></div>
        </div>
    </div>
</div>

<!-- Result Overlay -->
<div class="overlay" id="resultOverlay">
    <div class="result-card" id="resultCard"></div>
</div>

<script>
const PHASES=['led_test','motor_init','homing','rotation_360','feeding','sensor_check','bending','cutting'];
const PL={led_test:'LED Test',motor_init:'Motor Init',homing:'Homing',rotation_360:'360° Rotation',
feeding:'Feeding',sensor_check:'Sensor Check',bending:'Bending',cutting:'Cutting'};
const AXES=['BENDER','FEEDER','CUTTER'];
let currentTab='all',eventSource=null,bendData=[],errorCount=0,bendCount=0,startTime=0,timerInterval=null;
let targetCycles=3;

// Init phase grid
const pg=document.getElementById('phaseGrid');
PHASES.forEach(p=>{const d=document.createElement('div');d.className='phase-item';
d.innerHTML=`<span class="phase-dot off" id="pd_${p}"></span><span>${PL[p]}</span>`;pg.appendChild(d)});

// Init axis cards
const ac=document.getElementById('axisCards');
AXES.forEach(a=>{const d=document.createElement('div');d.className='axis-card';d.id='ax_'+a;
d.innerHTML=`<div class="name"><span>${a}</span><span class="state state-idle" id="axs_${a}">IDLE</span></div>
<div class="axis-row"><span class="k">Position</span><span class="v" id="axp_${a}">0</span></div>
<div class="axis-row"><span class="k">Target</span><span class="v" id="axt_${a}">0</span></div>
<div class="axis-row"><span class="k">Speed</span><span class="v" id="axv_${a}">0</span></div>`;
ac.appendChild(d)});

function addLog(text,cls='',source='all'){
const area=document.getElementById('logArea');
if(currentTab!=='all'&&currentTab!==source)return;
const d=document.createElement('div');d.className='log-line '+cls;d.textContent=text;
area.appendChild(d);if(area.children.length>500)area.removeChild(area.firstChild);
area.scrollTop=area.scrollHeight}

function switchTab(t,el){currentTab=t;
document.querySelectorAll('.log-tab').forEach(b=>b.classList.remove('active'));
el.classList.add('active');document.getElementById('logArea').innerHTML=''}

function updateSensor(id,val){const el=document.getElementById('s'+id);
el.textContent=val;el.className='val '+(val?'sensor-on':'sensor-off')}

function updateTimer(){if(!startTime)return;
const e=Math.floor((Date.now()-startTime)/1000);
document.getElementById('timerDisplay').textContent=
String(Math.floor(e/60)).padStart(2,'0')+':'+String(e%60).padStart(2,'0')}

function updateCycleBar(done,total){
const bar=document.getElementById('cycleBar');bar.innerHTML='';
for(let i=0;i<total;i++){const d=document.createElement('span');
d.className='cycle-dot'+(i<done?' done':'');bar.appendChild(d)}}

// ── Step-to-degree conversion (1.8° per full step, 128 microsteps) ──
function steps2deg(steps){return steps*(1.8/128)}

// ── Trend data ──
const TREND_MAX=100;
let trendActual=[],trendTarget=[];
let bendAxisState={pos:0,target:0,state:'IDLE'};
let rotateAxisState={pos:0,target:0,state:'IDLE'};

// ── SVG Dial Gauge ──
function drawDial(svgId,size,currentDeg,targetDeg,steps,state,label){
const svg=document.getElementById(svgId);
const cx=size/2,cy=size/2,r=size*0.4;
const homeZone=5; // ±5° highlight
const ns='http://www.w3.org/2000/svg';

svg.innerHTML='';

// Background circle
const bgCirc=document.createElementNS(ns,'circle');
bgCirc.setAttribute('cx',cx);bgCirc.setAttribute('cy',cy);bgCirc.setAttribute('r',r);
bgCirc.setAttribute('fill','none');bgCirc.setAttribute('stroke','#1a2744');bgCirc.setAttribute('stroke-width',size*0.06);
svg.appendChild(bgCirc);

// Home zone arc (±5°)
const homeStart=-homeZone,homeEnd=homeZone;
const drawArc=(startDeg,endDeg,color,width)=>{
const sr=(startDeg-90)*Math.PI/180,er=(endDeg-90)*Math.PI/180;
const x1=cx+r*Math.cos(sr),y1=cy+r*Math.sin(sr);
const x2=cx+r*Math.cos(er),y2=cy+r*Math.sin(er);
const large=Math.abs(endDeg-startDeg)>180?1:0;
const path=document.createElementNS(ns,'path');
path.setAttribute('d',`M${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2}`);
path.setAttribute('fill','none');path.setAttribute('stroke',color);path.setAttribute('stroke-width',width);
path.setAttribute('stroke-linecap','round');svg.appendChild(path)};

drawArc(homeStart,homeEnd,'#23863555',size*0.06);

// Major ticks every 30°, minor every 10°
for(let deg=-180;deg<=180;deg+=10){
const isMajor=deg%30===0;
const rad=(deg-90)*Math.PI/180;
const inner=r-(isMajor?size*0.07:size*0.04);
const outer=r+(isMajor?size*0.03:size*0.01);
const tick=document.createElementNS(ns,'line');
tick.setAttribute('x1',cx+inner*Math.cos(rad));tick.setAttribute('y1',cy+inner*Math.sin(rad));
tick.setAttribute('x2',cx+outer*Math.cos(rad));tick.setAttribute('y2',cy+outer*Math.sin(rad));
tick.setAttribute('stroke',isMajor?'#484f58':'#30363d');
tick.setAttribute('stroke-width',isMajor?1.5:0.8);svg.appendChild(tick);
if(isMajor&&size>150){
const lr=r+size*0.1;const txt=document.createElementNS(ns,'text');
txt.setAttribute('x',cx+lr*Math.cos(rad));txt.setAttribute('y',cy+lr*Math.sin(rad));
txt.setAttribute('text-anchor','middle');txt.setAttribute('dominant-baseline','middle');
txt.setAttribute('fill','#8b949e');txt.setAttribute('font-size',size*0.05);
txt.textContent=deg+'°';svg.appendChild(txt)}}

// Target needle (orange)
const tRad=(targetDeg-90)*Math.PI/180;
const tLen=r*0.85;
const tNeedle=document.createElementNS(ns,'line');
tNeedle.setAttribute('x1',cx);tNeedle.setAttribute('y1',cy);
tNeedle.setAttribute('x2',cx+tLen*Math.cos(tRad));tNeedle.setAttribute('y2',cy+tLen*Math.sin(tRad));
tNeedle.setAttribute('stroke','#d29922');tNeedle.setAttribute('stroke-width',2);
tNeedle.setAttribute('stroke-linecap','round');tNeedle.setAttribute('opacity','0.7');
svg.appendChild(tNeedle);

// Current needle (cyan)
const cRad=(currentDeg-90)*Math.PI/180;
const cLen=r*0.9;
const cNeedle=document.createElementNS(ns,'line');
cNeedle.setAttribute('x1',cx);cNeedle.setAttribute('y1',cy);
cNeedle.setAttribute('x2',cx+cLen*Math.cos(cRad));cNeedle.setAttribute('y2',cy+cLen*Math.sin(cRad));
cNeedle.setAttribute('stroke','#79c0ff');cNeedle.setAttribute('stroke-width',2.5);
cNeedle.setAttribute('stroke-linecap','round');svg.appendChild(cNeedle);

// Center dot
const dot=document.createElementNS(ns,'circle');
dot.setAttribute('cx',cx);dot.setAttribute('cy',cy);dot.setAttribute('r',size*0.025);
dot.setAttribute('fill','#c9d1d9');svg.appendChild(dot);

// Center text: degree value
const degTxt=document.createElementNS(ns,'text');
degTxt.setAttribute('x',cx);degTxt.setAttribute('y',cy+size*0.18);
degTxt.setAttribute('text-anchor','middle');degTxt.setAttribute('fill','#79c0ff');
degTxt.setAttribute('font-size',size*0.09);degTxt.setAttribute('font-weight','700');
degTxt.setAttribute('font-family','monospace');
degTxt.textContent=currentDeg.toFixed(1)+'°';svg.appendChild(degTxt);

// State badge
const stateTxt=document.createElementNS(ns,'text');
stateTxt.setAttribute('x',cx);stateTxt.setAttribute('y',cy+size*0.28);
stateTxt.setAttribute('text-anchor','middle');
stateTxt.setAttribute('fill',state==='MOVING'?'#58a6ff':'#484f58');
stateTxt.setAttribute('font-size',size*0.055);stateTxt.setAttribute('font-weight','700');
stateTxt.textContent=state;svg.appendChild(stateTxt)}

function updateBendDial(){
const deg=steps2deg(bendAxisState.pos);
const targetDeg=steps2deg(bendAxisState.target);
drawDial('bendDial',200,deg,targetDeg,bendAxisState.pos,bendAxisState.state);
document.getElementById('bendDialInfo').textContent=
bendAxisState.pos+' steps / '+deg.toFixed(1)+'°'}

function updateRotateDial(){
const deg=steps2deg(rotateAxisState.pos);
const targetDeg=steps2deg(rotateAxisState.target);
drawDial('rotateDial',140,deg,targetDeg,rotateAxisState.pos,rotateAxisState.state);
document.getElementById('rotateDialInfo').textContent=
rotateAxisState.pos+' steps / '+deg.toFixed(1)+'°'}

// ── Trend Chart ──
function drawTrendChart(){
const canvas=document.getElementById('trendCanvas'),ctx=canvas.getContext('2d');
const rect=canvas.parentElement.getBoundingClientRect();
const dpr=window.devicePixelRatio||1;
canvas.width=rect.width*dpr;canvas.height=rect.height*dpr;ctx.scale(dpr,dpr);
const w=rect.width,h=rect.height;ctx.clearRect(0,0,w,h);

const minDeg=-180,maxDeg=180,range=maxDeg-minDeg;
const pad={top:8,bottom:14,left:30,right:8};
const pw=w-pad.left-pad.right,ph=h-pad.top-pad.bottom;

// Grid lines and labels
ctx.strokeStyle='#21262d';ctx.lineWidth=0.5;
ctx.fillStyle='#8b949e';ctx.font='8px monospace';ctx.textAlign='right';
for(let deg=-180;deg<=180;deg+=90){
const y=pad.top+ph*(1-(deg-minDeg)/range);
ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(w-pad.right,y);ctx.stroke();
ctx.fillText(deg+'°',pad.left-3,y+3)}

// Zero line highlight
const zeroY=pad.top+ph*0.5;
ctx.strokeStyle='#30363d';ctx.lineWidth=1;
ctx.beginPath();ctx.moveTo(pad.left,zeroY);ctx.lineTo(w-pad.right,zeroY);ctx.stroke();

const drawLine=(data,color)=>{
if(data.length<2)return;
ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();
for(let i=0;i<data.length;i++){
const x=pad.left+(i/(TREND_MAX-1))*pw;
const y=pad.top+ph*(1-(data[i]-minDeg)/range);
i===0?ctx.moveTo(x,y):ctx.lineTo(x,y)}
ctx.stroke()};

drawLine(trendTarget,'#d29922');
drawLine(trendActual,'#58a6ff')}

// Init dials
updateBendDial();updateRotateDial();drawTrendChart();

function updateProtoStats(stats){
const el=document.getElementById('protoList');
const entries=Object.entries(stats).sort((a,b)=>b[1]-a[1]);
let html='';entries.forEach(([k,v])=>{
html+=`<div class="proto-row"><span class="cmd">${k}</span><span class="cnt">${v}</span></div>`});
const total=entries.reduce((s,[,v])=>s+v,0);
if(entries.length)html+=`<div class="proto-total proto-row"><span class="cmd">TOTAL</span><span class="cnt">${total}</span></div>`;
el.innerHTML=html}

function startTest(){
targetCycles=parseInt(document.getElementById('inCycles').value)||3;
const speed=document.getElementById('inSpeed').value;
const timeout=document.getElementById('inTimeout').value;
document.getElementById('logArea').innerHTML='';bendData=[];errorCount=0;bendCount=0;
trendActual=[];trendTarget=[];bendAxisState={pos:0,target:0,state:'IDLE'};
rotateAxisState={pos:0,target:0,state:'IDLE'};
updateBendDial();updateRotateDial();drawTrendChart();
PHASES.forEach(p=>document.getElementById('pd_'+p).className='phase-dot off');
['B','F0','F1','R','C'].forEach(s=>updateSensor(s,'—'));
AXES.forEach(a=>{document.getElementById('axp_'+a).textContent='0';
document.getElementById('axt_'+a).textContent='0';
document.getElementById('axv_'+a).textContent='0';
document.getElementById('axs_'+a).className='state state-idle';
document.getElementById('axs_'+a).textContent='IDLE'});
document.getElementById('stCycles').textContent='0 / '+targetCycles;
document.getElementById('stBends').textContent='0';
document.getElementById('stCmds').textContent='0';
document.getElementById('stCRC').textContent='0';
document.getElementById('stErrors').textContent='0';
document.getElementById('bendInfo').textContent='—';
document.getElementById('protoList').innerHTML='';
document.getElementById('resultOverlay').classList.remove('show');
updateCycleBar(0,targetCycles);

fetch(`/api/start?cycles=${targetCycles}&speed=${speed}&timeout=${timeout}`)
.then(r=>r.json()).then(d=>{if(d.ok){connectSSE();
document.getElementById('btnStart').style.display='none';
document.getElementById('btnStop').style.display='';
startTime=Date.now();timerInterval=setInterval(updateTimer,1000)}
else alert('Failed: '+d.error)})}

function stopTest(){fetch('/api/stop').then(r=>r.json())}

function connectSSE(){
if(eventSource)eventSource.close();
eventSource=new EventSource('/api/events');

eventSource.addEventListener('status',e=>{const d=JSON.parse(e.data);
const badge=document.getElementById('statusBadge');
if(d.state==='running'){badge.className='badge badge-running';badge.textContent='RUNNING'}
else if(d.state==='completed'){badge.textContent='DONE';
document.getElementById('btnStart').style.display='';
document.getElementById('btnStop').style.display='none';
clearInterval(timerInterval)}
addLog('[STATUS] '+d.message,'phase')});

eventSource.addEventListener('kc_log',e=>{const d=JSON.parse(e.data);let cls='';
if(d.line.includes('ERROR'))cls='error';
else if(d.line.includes('Check Sensors'))cls='sensor';
else if(d.line.includes('Bending'))cls='bend';
else if(d.line.startsWith('*')||d.line.startsWith('>'))cls='phase';
addLog(d.line,cls,'kc')});

eventSource.addEventListener('sim_log',e=>{const d=JSON.parse(e.data);
addLog(d.line,'sim','sim')});

eventSource.addEventListener('phases',e=>{const d=JSON.parse(e.data);
Object.entries(d).forEach(([k,v])=>{
document.getElementById('pd_'+k).className='phase-dot '+(v?'on':'off')})});

eventSource.addEventListener('sensors',e=>{const d=JSON.parse(e.data);
Object.entries(d).forEach(([k,v])=>updateSensor(k,v))});

eventSource.addEventListener('axis',e=>{const d=JSON.parse(e.data);
if(!AXES.includes(d.name))return;
document.getElementById('axp_'+d.name).textContent=d.pos.toLocaleString();
document.getElementById('axt_'+d.name).textContent=d.target.toLocaleString();
document.getElementById('axv_'+d.name).textContent=d.speed;
const se=document.getElementById('axs_'+d.name);
se.className='state state-'+(d.state==='MOVING'?'moving':'idle');
se.textContent=d.state;
// Update dials
if(d.name==='BENDER'){bendAxisState={pos:d.pos,target:d.target,state:d.state};
updateBendDial();
trendActual.push(steps2deg(d.pos));trendTarget.push(steps2deg(d.target));
if(trendActual.length>TREND_MAX){trendActual.shift();trendTarget.shift()}
drawTrendChart()}
else if(d.name==='FEEDER'){/* ROTATE axis not present in Phase 1 sim, use FEEDER as placeholder */}
});

eventSource.addEventListener('bend',e=>{const d=JSON.parse(e.data);
bendData.push(d);bendCount=d.count||bendCount+1;
document.getElementById('stBends').textContent=bendCount;
document.getElementById('bendInfo').textContent=`pos=${d.pos} (${d.deg.toFixed(1)}°)`;
drawBendChart()});

eventSource.addEventListener('cycle',e=>{const d=JSON.parse(e.data);
document.getElementById('stCycles').textContent=d.count+' / '+(d.target||targetCycles);
updateCycleBar(d.count,d.target||targetCycles)});

eventSource.addEventListener('stats',e=>{const d=JSON.parse(e.data);
document.getElementById('stCmds').textContent=d.cmd_total;
document.getElementById('stCRC').textContent=d.crc_errors;
if(d.protocol)updateProtoStats(d.protocol)});

eventSource.addEventListener('error_event',e=>{const d=JSON.parse(e.data);
errorCount++;document.getElementById('stErrors').textContent=errorCount;
addLog('[ERROR] '+d.message,'error')});

eventSource.addEventListener('result',e=>{const d=JSON.parse(e.data);showResult(d)});

eventSource.onerror=()=>{setTimeout(()=>{
if(document.getElementById('btnStop').style.display!=='none')connectSSE()},2000)}}

function showResult(d){
const card=document.getElementById('resultCard');
const cls=d.result==='PASS'?'pass':'fail';
let ph=Object.entries(d.phases).map(([k,v])=>
`<tr><td>${PL[k]}</td><td style="color:${v?'#3fb950':'#f85149'}">${v?'PASS':'FAIL'}</td></tr>`).join('');
let pr=Object.entries(d.protocol_stats||{}).sort((a,b)=>b[1]-a[1])
.map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join('');
let ax='';if(d.axes){Object.entries(d.axes).forEach(([k,v])=>{
ax+=`<tr><td>${k}</td><td>pos=${v.pos} ${v.state}</td></tr>`})}
card.innerHTML=`
<h2 class="${cls}">Result: ${d.result}</h2>
<div style="color:var(--dim);margin-bottom:10px;font-size:13px">
${d.elapsed}s elapsed &bull; ${d.cycles} cycles &bull; ${d.bend_count||0} bends &bull; ${d.cmd_total||0} commands</div>
<div class="section-title" style="margin:10px 0 4px">Phases</div><table>${ph}</table>
${ax?`<div class="section-title" style="margin:10px 0 4px">Final Axis State</div><table>${ax}</table>`:''}
${d.errors&&d.errors.length?`<div class="section-title" style="margin:10px 0 4px;color:var(--red)">Errors (${d.errors.length})</div>
<div style="font-size:11px;color:var(--red);max-height:80px;overflow-y:auto">
${d.errors.map(e=>`<div>${e}</div>`).join('')}</div>`:''}
${pr?`<div class="section-title" style="margin:10px 0 4px">Protocol</div><table>${pr}</table>`:''}
<button class="close-btn" onclick="document.getElementById('resultOverlay').classList.remove('show')">Close</button>`;
document.getElementById('resultOverlay').classList.add('show');
const badge=document.getElementById('statusBadge');badge.className='badge badge-'+cls;badge.textContent=d.result}

window.addEventListener('resize',()=>{drawTrendChart();updateBendDial();updateRotateDial()});
</script>
</body>
</html>
"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/api/start":
            self._handle_start(parse_qs(parsed.query))
        elif path == "/api/stop":
            self._handle_stop()
        elif path == "/api/events":
            self._handle_sse()
        elif path == "/api/status":
            self._handle_status()
        else:
            self.send_error(404)

    def _serve_html(self):
        data = DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_start(self, params):
        global g_test_proc
        with g_test_lock:
            if g_test_proc and g_test_proc.running:
                self._json_response({"ok": False, "error": "Test already running"})
                return

            cycles = int(params.get("cycles", [3])[0])
            speed = float(params.get("speed", [100])[0])
            timeout = int(params.get("timeout", [120])[0])

            g_test_proc = TestRunner(g_build_dir, speed, cycles, timeout)
            ok = g_test_proc.start()
            self._json_response({"ok": ok})

    def _handle_stop(self):
        global g_test_proc
        with g_test_lock:
            if g_test_proc and g_test_proc.running:
                threading.Thread(target=g_test_proc.stop, daemon=True).start()
                self._json_response({"ok": True})
            else:
                self._json_response({"ok": False, "error": "No test running"})

    def _handle_status(self):
        global g_test_proc
        with g_test_lock:
            if g_test_proc:
                self._json_response({
                    "running": g_test_proc.running,
                    "phases": g_test_proc.phases,
                    "cycles": g_test_proc.cycle_count,
                })
            else:
                self._json_response({"running": False})

    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = queue.Queue(maxsize=300)
        with g_event_lock:
            g_event_queues.append(q)

        try:
            while True:
                try:
                    event_type, data = q.get(timeout=15)
                    sse_type = "error_event" if event_type == "error" else event_type
                    self.wfile.write(f"event: {sse_type}\ndata: {data}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with g_event_lock:
                if q in g_event_queues:
                    g_event_queues.remove(q)

    def _json_response(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ThreadedHTTPServer(http.server.HTTPServer):
    """Handle each request in a separate thread."""
    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread,
                             args=(request, client_address))
        t.daemon = True
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def main():
    global g_build_dir

    parser = argparse.ArgumentParser(description="KC Test Web Dashboard")
    parser.add_argument("--port", type=int, default=8080,
                        help="HTTP port (default: 8080)")
    parser.add_argument("--build-dir", default="build-host",
                        help="Build directory (default: build-host)")
    args = parser.parse_args()

    g_build_dir = args.build_dir
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    server = ThreadedHTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"KC Test Dashboard running at:")
    print(f"  http://localhost:{args.port}")
    print(f"  Build dir: {g_build_dir}")
    print(f"\nPress Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
