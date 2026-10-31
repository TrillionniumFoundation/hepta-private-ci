"""Two-process fit/selection matrices; final latency never uses this runner."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from experiments.multimodal_output_portfolio.abc_next.temporal.audit import sha256, write_json
from .tasks import manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("fit",), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    children = []
    for index in range(2):
        worker = args.output / f"worker-{index}"
        log = (args.output / f"worker-{index}.log").open("xb")
        command = [sys.executable, "-m", "experiments.multimodal_output_portfolio.abc_followup.temporal.run",
                   "--role", args.role, "--output", str(worker), "--assets", str(args.assets),
                   "--shards", "2", "--shard-index", str(index)]
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        children.append((process, log, worker, command))
    receipts = []
    for process, log, worker, command in children:
        pid, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
        log.close()
        receipt = {"pid": pid, "exit_code": process.returncode, "command": command,
                   "cpu_seconds": usage.ru_utime + usage.ru_stime, "peak_rss_kib": usage.ru_maxrss}
        receipts.append(receipt)
        write_json(args.output / f"child-{pid}.json", receipt)
    if any(r["exit_code"] != 0 for r in receipts):
        write_json(args.output / "failure.json", {"role": args.role, "children": receipts})
        raise RuntimeError("Matrix worker failed; retain all partial observations")
    indices, worker_results = [], []
    for _, _, worker, _ in children:
        worker_results.append(json.loads((worker / "complete.json").read_text()))
        indices.extend((worker / "index.jsonl").read_text().splitlines())
    with (args.output / "index.jsonl").open("x") as stream:
        stream.write("\n".join(indices) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    write_json(args.output / "start.json", {"role": args.role, "source_groups": len(manifest()["roles"][args.role]),
               "source_manifest": manifest(), "workers": 2,
               "clock_scope": "parent includes launch, load, all workers, merge; final report write excluded"})
    result = {"role": args.role, "complete": True,
              "source_groups": sum(r["source_groups"] for r in worker_results),
              "requests": sum(r["requests"] for r in worker_results), "failures": 0,
              "index_sha256": sha256(args.output / "index.jsonl"),
              "wall_ns": time.perf_counter_ns() - wall,
              "cpu_ns": time.process_time_ns() - cpu + round(sum(r["cpu_seconds"] for r in receipts) * 1e9),
              "children": receipts, "worker_results": worker_results,
              "parallel_matrix_cost_not_serial_request_latency": True}
    write_json(args.output / "complete.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
