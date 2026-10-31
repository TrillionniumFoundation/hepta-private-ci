"""Smoke-test actual spawned workers using two development groups only."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path

from .audit import write_json
from .parallel_matrix import execute_shard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "external-assets", "policies", "freeze", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = json.loads((args.freeze / "sources.json").read_text())["roles"]["development"][:2]
    cpus = sorted(os.sched_getaffinity(0))[-2:]
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(execute_shard, shard, [(shard, sources[shard])], vars(args), cpus[shard])
                   for shard in range(2)]
        rows = [future.result() for future in futures]
    report = {"role": "development", "groups": 2, "cases": sum(map(len, rows)),
              "rows": rows, "assigned_cpus": cpus, "evaluation_sources_used": False}
    write_json(args.output / "development_parallel.json", report)
    print(json.dumps({"development_groups": 2, "actual_cases": report["cases"], "passed": True}))


if __name__ == "__main__":
    main()
