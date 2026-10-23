"""Single-worker supervisor; no data/network operations or model imports here."""

import argparse
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

from .cost import cpu_ns


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--data")
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.smoke:
        if args.data or args.out:
            parser.error("no-data smoke accepts no data/output target")
        from .run import smoke
        print(json.dumps(smoke(), sort_keys=True))
        return 0
    if not args.data or not args.out:
        parser.error("run requires local --data and new --out")
    from .run import preflight
    preflight(args.data, args.out)  # no marker on missing data or bad source
    cap_ns, cap_rss = 1800_000_000_000, 2**31
    pid = os.fork()
    if pid == 0:
        env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                   MKL_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
        os.execve(sys.executable, [sys.executable, "-m", "fashion_research.run",
                                  "--worker", "--data", args.data, "--out", args.out], env)
    ticks = os.sysconf("SC_CLK_TCK")
    stop_reason = None
    while True:
        child, status, usage = os.wait4(pid, os.WNOHANG)
        if child:
            break
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().split()
            worker_ns = (int(fields[13]) + int(fields[14])) * 10**9 // ticks
            memory = Path(f"/proc/{pid}/status").read_text().splitlines()
            peak = max(int(line.split()[1]) * 1024 for line in memory
                       if line.startswith(("VmRSS:", "VmHWM:")))
            if stop_reason is None and (worker_ns + time.process_time_ns() > cap_ns or peak > cap_rss):
                stop_reason = "supervisor actual CPU/RSS cap exceeded"
                os.kill(pid, signal.SIGTERM)
        except (FileNotFoundError, ProcessLookupError, ValueError):
            pass
        time.sleep(0.1)
    code = os.waitstatus_to_exitcode(status)
    # wait4 reaps the child, so RUSAGE_CHILDREN now includes its complete CPU.
    total = cpu_ns()
    if total > cap_ns or usage.ru_maxrss * 1024 > cap_rss:
        stop_reason = stop_reason or "complete supervisor+worker CPU/RSS cap exceeded"
    receipt = {"schema": "hepta.fashion-D-supervisor.v1", "worker_exit_code": code,
               "exit_code": code if code else (1 if stop_reason else 0),
               "process_plus_descendant_CPU_ns_before_receipt": total,
               "parent_CPU_ns": time.process_time_ns(),
               "worker_CPU_ns": round((usage.ru_utime + usage.ru_stime) * 1e9),
               "worker_peak_RSS_bytes": usage.ru_maxrss * 1024,
               "stop_reason": stop_reason,
               "boundary": "Includes launcher and reaped worker CPU; final receipt serialization is followed by a final cap check. Independent publication/review is separate R&D."}
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    (output / "supervisor.json").write_text(json.dumps(receipt, indent=2) + "\n")
    retained = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    rss_bound = (usage.ru_maxrss + resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    if cpu_ns() > cap_ns or retained > 2**31 or rss_bound > cap_rss:
        receipt.update(exit_code=1, stop_reason="complete CPU/retained/RSS tail cap exceeded",
                       retained_bytes_after_first_receipt=retained,
                       parent_plus_worker_peak_RSS_upper_bound_bytes=rss_bound)
        (output / "supervisor.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return 1
    return receipt["exit_code"] if receipt["exit_code"] >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
