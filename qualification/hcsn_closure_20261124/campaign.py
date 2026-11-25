"""Linux operator campaign; fixed roster, fresh workers, then one global seal."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

import torch

from .provenance import create, digest, identity, load, prepare, read, seal


def stage(root, p, action, workers):
    wall, cpu = time.perf_counter(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)

    def one(slot):
        started = time.perf_counter()
        row = {"slot": slot["id"], "returncode": None, "error": None}
        try:
            command = [sys.executable, "-m", __package__ + ".runner", action,
                       "--root", str(root), "--slot", slot["id"]]
            env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
            with (root / (slot["id"] + "." + action + ".log")).open("x") as log:
                child = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                       env=env, timeout=2400, check=False)
            row["returncode"] = child.returncode
        except Exception:
            row["error"] = traceback.format_exc()
        finally:
            row["launch_through_exit_wall_seconds"] = time.perf_counter() - started
            directory = root / slot["id"]
            directory.mkdir(exist_ok=True)
            create(directory / ("parent_cost.json" if action == "fit" else "test_parent_cost.json"), row)
        print(str({"stage": action, **row}), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, p["slots"]))
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"stage": action, "workers": workers, "attempts": rows,
               "wall_seconds": time.perf_counter() - wall,
               "driver_cpu_seconds": time.process_time() - cpu,
               "children_cpu_seconds_including_shutdown": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
               "energy_joules_process": None}
    create(root / (action.upper() + "_EXECUTION.json"), receipt)
    return receipt


def run(root, workers):
    p = load(root)
    create(root / "RUN_CLAIM.json", {"protocol_sha256": identity(p), "workers": workers})
    wall, cpu = time.perf_counter(), time.process_time()
    status, error = "failed", None
    try:
        stage(root, p, "fit", workers)
        seal(root, p)
        create(root / "TEST_CLAIM.json", {"seal_sha256": digest(root / "SEAL.json"),
                                          "protocol_sha256": identity(p)})
        tested = stage(root, p, "test", workers)
        if any(row["returncode"] != 0 or row["error"] is not None for row in tested["attempts"]):
            raise RuntimeError("holdout workers failed; complete receipts retained")
        for slot in p["slots"]:
            terminal = read(root / slot["id"] / "test_result.json")
            if terminal["slot"] != slot or terminal["status"] not in ("evaluated", "unavailable"):
                raise ValueError("missing or invalid terminal test result")
        status = "completed"
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        create(root / "CAMPAIGN_RECEIPT.json", {"status": status, "error": error,
               "wall_seconds": time.perf_counter() - wall,
               "driver_cpu_seconds": time.process_time() - cpu,
               "energy_joules_process": None,
               "scope": "driver only; separate stage receipts include complete child CPU"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=9)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        raise ValueError("campaign concurrency must lie in 1..12")
    torch.set_num_threads(1)
    if args.action == "prepare":
        p = prepare(args.root)
        print({"protocol_sha256": identity(p), "slots": len(p["slots"]),
               "source_files": len(p["source_hashes"]), "holdout_constructed": False}, flush=True)
    else:
        run(args.root, args.workers)


if __name__ == "__main__":
    main()
