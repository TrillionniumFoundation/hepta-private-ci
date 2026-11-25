"""Linux-only fresh-worker coordinator; all nine training slots precede test."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

import torch

from .provenance import check_seal, create, identity, load, prepare, read, seal


def worker(root, action, slot, smoke=False):
    directory = root/slot["id"]
    directory.mkdir(exist_ok=True) if action == "test" else None
    started, error, code = time.perf_counter(), None, None
    logpath = root/(action+"-"+slot["id"]+".log")
    command = [sys.executable, "-m", "qualification.hcsn_closure_av_20261125.runner", action,
               "--root", str(root), "--slot", slot["id"]]+(["--smoke"] if smoke else [])
    try:
        with logpath.open("x") as log:
            code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=1800 if action == "fit" else 600).returncode
    except Exception:
        error = traceback.format_exc()
    finally:
        directory.mkdir(exist_ok=True)
        row = {"slot": slot, "action": action, "returncode": code, "error": error,
               "parent_wall_seconds": time.perf_counter()-started, "command": command}
        create(directory/("parent_cost.json" if action == "fit" else "test_parent_cost.json"), row)
        print(str({"slot": slot["id"], "action": action, "returncode": code}), flush=True)
    return row


def stage(root, action, slots, parallel, smoke=False):
    start, cpu = time.perf_counter(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        rows = list(pool.map(lambda slot: worker(root, action, slot, smoke), slots))
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"stage": action, "smoke": smoke, "workers": rows, "wall_seconds": time.perf_counter()-start,
        "driver_cpu_seconds": time.process_time()-cpu,
        "children_cpu_seconds": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        "largest_child_peak_rss_bytes": after.ru_maxrss*1024,
        "cost_scope": "All fresh children including import/shutdown. Nested worker/body costs are not added again; peak RSS is per child, not concurrent total.", "energy_joules": None}
    create(root/(("SMOKE_" if smoke else "")+action.upper()+"_EXECUTION.json"), receipt)
    if any(r["error"] is not None or r["returncode"] not in ((0, 1) if action == "fit" else (0,)) for r in rows):
        raise RuntimeError("worker execution incomplete; no permission to evaluate a partial roster")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "smoke", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--parallel", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.parallel <= 6:
        raise ValueError("bounded concurrency required")
    torch.set_num_threads(1)
    if args.action == "prepare":
        if args.data is None:
            raise ValueError("prepared dataset required")
        prepare(args.root, args.data)
        return 0
    p = load(args.root)
    if args.action == "smoke":
        chosen = [next(s for s in p["slots"] if s["arm"] == arm) for arm in ("hcsn", "transformer", "lif")]
        stage(args.root, "fit", chosen, args.parallel, True)
        return 0
    status, error = "failed", None
    started, cpu = time.perf_counter(), time.process_time()
    try:
        stage(args.root, "fit", p["slots"], args.parallel)
        seal(args.root, p)
        seal_sha = check_seal(args.root, p)
        create(args.root/"TEST_CLAIM.json", {"protocol_sha256": identity(p), "seal_sha256": seal_sha})
        stage(args.root, "test", p["slots"], args.parallel)
        results = [read(args.root/s["id"]/"test_result.json") for s in p["slots"]]
        if any(r["slot"] != s or r["protocol_sha256"] != identity(p) or r["seal_sha256"] != seal_sha
               for s, r in zip(p["slots"], results)):
            raise ValueError("final test roster identity mismatch")
        for s, result in zip(p["slots"], results):
            expected = "skipped_failed_fit" if read(args.root/s["id"]/"result.json")["status"] == "failed" else "evaluated"
            if result["status"] != expected or read(args.root/s["id"]/"test_worker_cost.json")["error"] is not None:
                raise ValueError("test stage did not reach the declared terminal status")
        create(args.root/"FINAL_RESULTS.json", {"protocol_sha256": identity(p), "seal_sha256": seal_sha, "results": results})
        status = "completed"
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        create(args.root/"CAMPAIGN_RECEIPT.json", {"status": status, "error": error,
            "wall_seconds": time.perf_counter()-started, "driver_cpu_seconds": time.process_time()-cpu,
            "scope": "Coordinator only. See disjoint fit/test child-stage CPU; do not add nested worker/body costs.", "energy_joules": None})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
