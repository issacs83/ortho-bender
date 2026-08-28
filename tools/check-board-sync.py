"""Is the board running exactly what the checkout says it is?

    python3 tools/check-board-sync.py <board-ip>


Docs were checked already. This compares the shipped Python source and
the built frontend, because a board running yesterday's motor_service
while the docs describe today's API is the failure mode that wastes a
CAM developer's afternoon.
"""
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
BOARD_IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.77.2"
BASE = f"http://{BOARD_IP}:8000"

SSH = ["sshpass", "-p", "ortho-bender", "ssh",
       "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "StrictHostKeyChecking=no",
       f"root@{BOARD_IP}"]


def remote_md5(path):
    r = subprocess.run(SSH + [f"md5sum {path} 2>/dev/null || echo MISSING"],
                       capture_output=True, text=True, timeout=60)
    out = r.stdout.strip().split()
    return out[0] if out and out[0] != "MISSING" else None


def local_md5(p: Path):
    return hashlib.md5(p.read_bytes()).hexdigest()


# ---- server source -------------------------------------------------------
SRC = ROOT / "src/app/server"
print("=== 서버 소스 대조 (repo main vs board) ===")
mismatch, missing = [], []
for f in sorted(SRC.rglob("*.py")):
    if "__pycache__" in str(f) or "/tests/" in str(f):
        continue
    rel = f.relative_to(SRC)
    rm = remote_md5(f"/opt/ortho-bender/server/{rel}")
    lm = local_md5(f)
    if rm is None:
        missing.append(str(rel))
    elif rm != lm:
        mismatch.append(str(rel))
print(f"  검사 {len(list(p for p in SRC.rglob('*.py') if '__pycache__' not in str(p) and '/tests/' not in str(p)))}개"
      f"  불일치 {len(mismatch)}  누락 {len(missing)}")
for m in mismatch:
    print("    *** 다름:", m)
for m in missing:
    print("    *** 보드에 없음:", m)

# ---- frontend bundle -----------------------------------------------------
print("\n=== 프론트엔드 번들 ===")
dist = ROOT / "src/app/frontend/dist"
local_assets = sorted((dist / "assets").glob("*.js")) if dist.exists() else []
if local_assets:
    name = local_assets[0].name
    rm = remote_md5(f"/opt/ortho-bender/frontend-dist/assets/{name}")
    lm = local_md5(local_assets[0])
    print(f"  {name}: {'일치' if rm == lm else '*** 다름/없음'}")
else:
    print("  (로컬 빌드 없음 — 재빌드 후 비교 필요)")

# ---- docs ---------------------------------------------------------------
print("\n=== SDK 문서 ===")
stale = []
for f in sorted((ROOT / "docs/sdk").glob("*.md")):
    try:
        url = f"{BASE}/api/docs/file/sdk/{f.name}"
        remote = json.load(urllib.request.urlopen(url, timeout=10))["data"]["content"]
        same = (hashlib.md5(f.read_text(encoding="utf-8").encode()).hexdigest()
                == hashlib.md5(remote.encode()).hexdigest())
        if not same:
            stale.append(f.name)
    except Exception as exc:
        stale.append(f"{f.name} ({exc})")
print(f"  7개 중 불일치 {len(stale)}")
for s in stale:
    print("    ***", s)

# ---- live API behaviour --------------------------------------------------
print("\n=== 보드 API 동작 확인 ===")
for path, needle in (("/api/motor/protection", "run_cs_effective"),
                     ("/api/motor/stallguard", "sgt"),
                     ("/api/motor/status", "sg_value")):
    try:
        body = urllib.request.urlopen(BASE + path, timeout=10).read().decode()
        print(f"  {path:26s} {'O' if needle in body else '*** ' + needle + ' 없음'}")
    except Exception as exc:
        print(f"  {path:26s} 실패: {exc}")

total = len(mismatch) + len(missing) + len(stale)
print(f"\n요약: 소스 불일치 {len(mismatch) + len(missing)}건, 문서 불일치 {len(stale)}건")
print("보드는 main과" + (" 일치합니다." if total == 0 else f" {total}건 어긋나 있습니다."))
