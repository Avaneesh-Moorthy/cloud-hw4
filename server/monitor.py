"""
monitor.py - resource sampler for the web-server VM (used in the stress test).

Every --interval seconds it records, from /proc (no extra packages needed):
  cpu_pct    whole-VM CPU busy %   (user+system+irq+softirq, of all vCPUs)
  steal_pct  CPU time the hypervisor gave to other VMs (e2 shared-core VMs)
  mem_mb     VM memory in use (MemTotal - MemAvailable)
  rss_mb     resident memory of the web-server process
  threads    threads in the web-server process (ThreadingHTTPServer: 1 per open request)
  rx_kBps / tx_kBps   network receive / transmit, kilobytes per second
  req_s      requests completed per second (from the server's stats file)
  ok_s, err5xx         200 responses per second, total 5xx since start

Usage:  python3 monitor.py --seconds 180 --out /var/tmp/mon_2clients.csv
"""
import argparse
import json
import subprocess
import time


def cpu():
    v = list(map(int, open("/proc/stat").readline().split()[1:]))
    user, nice, system, idle, iowait, irq, softirq, steal = (v + [0] * 8)[:8]
    busy = user + nice + system + irq + softirq
    return busy, idle + iowait, steal, busy + idle + iowait + steal


def mem_mb():
    m = {}
    for line in open("/proc/meminfo"):
        k, val = line.split(":")
        m[k] = int(val.split()[0])
    return (m["MemTotal"] - m["MemAvailable"]) / 1024, m["MemTotal"] / 1024


def net():
    rx = tx = 0
    for line in open("/proc/net/dev").readlines()[2:]:
        name, data = line.split(":")
        if name.strip() == "lo":
            continue
        f = data.split()
        rx += int(f[0])
        tx += int(f[8])
    return rx, tx


def proc(pid):
    rss = thr = 0
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) / 1024
            elif line.startswith("Threads:"):
                thr = int(line.split()[1])
    except OSError:
        pass
    return rss, thr


def stats(path):
    try:
        d = json.load(open(path))
        five = sum(v for k, v in d["by_status"].items() if k.startswith("5") and k != "501")
        return d["requests"], d["by_status"].get("200", 0), five
    except (OSError, ValueError, KeyError):
        return 0, 0, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--service", default="hw4-web")
    ap.add_argument("--stats-file", default="/var/tmp/hw4_stats.json")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    pid = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", a.service],
                         capture_output=True, text=True).stdout.strip() or "0"
    rows = []
    b0, i0, s0, t0 = cpu()
    rx0, tx0 = net()
    r0, ok0, _ = stats(a.stats_file)
    start = last = time.time()
    while time.time() - start < a.seconds:
        time.sleep(a.interval)
        now = time.time()
        dt = now - last
        b, i, s, t = cpu()
        rx, tx = net()
        r, ok, e5 = stats(a.stats_file)
        used, total = mem_mb()
        rss, thr = proc(pid)
        dtot = max(t - t0, 1)
        rows.append({"t": round(now - start, 1),
                     "cpu_pct": round(100 * (b - b0) / dtot, 1),
                     "steal_pct": round(100 * (s - s0) / dtot, 1),
                     "mem_mb": round(used, 1), "mem_total_mb": round(total),
                     "rss_mb": round(rss, 1), "threads": thr,
                     "rx_kBps": round((rx - rx0) / dt / 1024, 1),
                     "tx_kBps": round((tx - tx0) / dt / 1024, 1),
                     "req_s": round((r - r0) / dt, 1), "ok_s": round((ok - ok0) / dt, 1),
                     "err5xx": e5})
        b0, i0, s0, t0, rx0, tx0, r0, ok0, last = b, i, s, t, rx, tx, r, ok, now

    with open(a.out, "w") as f:
        f.write(",".join(rows[0].keys()) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row.values()) + "\n")

    def avg(k): return sum(r[k] for r in rows) / len(rows)
    def peak(k): return max(r[k] for r in rows)
    print(f"{a.out}: {len(rows)} samples over {a.seconds}s")
    for k in ("cpu_pct", "steal_pct", "mem_mb", "rss_mb", "threads", "rx_kBps", "tx_kBps", "req_s"):
        print(f"  {k:10s} avg {avg(k):9.1f}   peak {peak(k):9.1f}")
    print(f"  5xx errors (cumulative): {rows[-1]['err5xx']}")


if __name__ == "__main__":
    main()
