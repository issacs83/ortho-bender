"""Find the bench on the network by its API port rather than a fixed IP.

The static 192.168.77.2 belongs to the board's onboard eth0. A USB
Ethernet adapter or a WiFi join comes up as a different interface with a
different address, so the address we have written down stops being the
one that answers.
"""
import concurrent.futures
import socket
import sys

# Pass subnets to narrow the search: tools/find-board.py 10.0.0
SUBNETS = sys.argv[1:] or ["192.168.219", "192.168.77", "192.168.0",
                           "192.168.1"]
PORT = 8000


def probe(ip):
    s = socket.socket()
    s.settimeout(0.6)
    try:
        s.connect((ip, PORT))
        return ip
    except OSError:
        return None
    finally:
        s.close()


found = []
for net in SUBNETS:
    targets = [f"{net}.{i}" for i in range(1, 255)]
    print(f"scanning {net}.0/24 for port {PORT} ...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=256) as ex:
        for r in ex.map(probe, targets):
            if r:
                found.append(r)
                print(f"  OPEN  {r}:{PORT}")

if not found:
    print("\nnothing answering on port 8000 in", ", ".join(SUBNETS))
else:
    import json
    import urllib.request
    print()
    for ip in found:
        try:
            u = f"http://{ip}:{PORT}/api/system/version"
            d = json.load(urllib.request.urlopen(u, timeout=4))
            print(f"  {ip} -> {json.dumps(d)[:160]}")
        except Exception as exc:
            print(f"  {ip} -> port open but not the SDK ({exc})")
