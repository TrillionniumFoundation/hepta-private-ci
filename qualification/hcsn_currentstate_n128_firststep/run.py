"""Execute the sole source-bound N128 first-step candidate/oracle comparison."""

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

from qualification.hcsn_currentstate_n128_engineering import candidate

from . import candidate_step, oracle_step
from .compare import compare, jsonl


def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    capsule, candidate_cost = candidate_step.run(
        args.law, args.metadata, args.npz, args.roster
    )
    oracle, oracle_cost = oracle_step.run(args.law, args.metadata, args.npz)
    candidate_rows = candidate.coordinate_lines(capsule)
    oracle_rows = oracle_step.coordinate_lines(oracle)
    comparison = compare(candidate_rows, oracle_rows)
    if comparison["coordinates"] != 18_528 or not comparison["passed"]:
        raise ArithmeticError(json.dumps(comparison, sort_keys=True))
    raw = candidate.dump(capsule)
    restored = candidate.load(raw)
    if (
        candidate.dump(restored) != raw
        or candidate.coordinate_lines(restored) != candidate_rows
    ):
        raise ArithmeticError("cold container is not byte-exact")
    (output / "CANDIDATE-COORDINATES.jsonl").write_text(jsonl(candidate_rows))
    (output / "ORACLE-COORDINATES.jsonl").write_text(jsonl(oracle_rows))
    (output / "CAPSULE.bin").write_bytes(raw)
    result = {
        "identity": args.identity,
        "unique_execution_key": args.key,
        "source_commit": args.source_commit,
        "status": "PASS_BOUNDED_N128_FIRSTSTEP_ONLY",
        "qualification": False,
        "time": [1, 1000],
        "comparison": comparison,
        "cold_container_bytes_exact": True,
        "candidate": candidate_cost,
        "oracle": oracle_cost,
        "calls": {
            "candidate_dynamic_steps": 1,
            "candidate_matrix_exponentials": 2,
            "oracle_dynamic_steps": 1,
            "oracle_matrix_exponentials": 2,
            "torch_operations": 0,
            "optimizer_updates": 0,
        },
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "remaining_open": [
            "later warm/coarse/cold times",
            "second-cycle feedback",
            "N256/N512 dynamics",
            "full-network training",
            "finite-domain qualification",
            "asynchronous complete cost",
        ],
        "all_closed": False,
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    artifacts = {
        path.name: {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(output.iterdir())
    }
    (output / "ARTIFACTS.json").write_text(
        json.dumps(artifacts, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(result, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    for name in (
        "law",
        "metadata",
        "npz",
        "roster",
        "output",
        "identity",
        "key",
        "source_commit",
    ):
        parser.add_argument(f"--{name.replace('_', '-')}", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
