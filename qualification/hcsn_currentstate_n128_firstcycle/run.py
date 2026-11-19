"""Execute the bounded N128 first-cycle candidate/oracle comparison."""

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

from qualification.hcsn_currentstate_n128_engineering import candidate
from qualification.hcsn_currentstate_n128_firststep.compare import compare, jsonl
from qualification.hcsn_currentstate_n128_firststep.oracle_step import coordinate_lines

from . import candidate_cycle, oracle_cycle


EXPECTED_CAPSULE_COORDINATES = (1376, 18528, 35680, 155702, 189992)
EXPECTED_TOTAL = sum(EXPECTED_CAPSULE_COORDINATES)


def prefixed(rows, order):
    return [dict(row, key=["capsule", order, *row["key"]]) for row in rows]


def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    capsules, candidate_cost = candidate_cycle.run(
        args.law, args.metadata, args.npz, args.roster
    )
    oracle, oracle_cost = oracle_cycle.run(args.law, args.metadata, args.npz)
    candidate_rows = []
    oracle_rows = []
    capsule_checks = []
    for order, (left, right, expected) in enumerate(
        zip(capsules, oracle, EXPECTED_CAPSULE_COORDINATES)
    ):
        left_rows = candidate.coordinate_lines(left)
        right_rows = coordinate_lines(right)
        if len(left_rows) != expected or len(right_rows) != expected:
            raise ArithmeticError(f"capsule {order} denominator")
        raw = candidate.dump(left)
        restored = candidate.load(raw)
        exact = candidate.dump(restored) == raw
        if not exact or candidate.coordinate_lines(restored) != left_rows:
            raise ArithmeticError(f"capsule {order} cold bytes")
        (output / f"CAPSULE-{order}.bin").write_bytes(raw)
        capsule_checks.append(
            {
                "order": order,
                "coordinates": expected,
                "cold_container_bytes_exact": exact,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        candidate_rows.extend(prefixed(left_rows, order))
        oracle_rows.extend(prefixed(right_rows, order))
    comparison = compare(candidate_rows, oracle_rows)
    if comparison["coordinates"] != EXPECTED_TOTAL or not comparison["passed"]:
        raise ArithmeticError(json.dumps(comparison, sort_keys=True))
    (output / "CANDIDATE-COORDINATES.jsonl").write_text(jsonl(candidate_rows))
    (output / "ORACLE-COORDINATES.jsonl").write_text(jsonl(oracle_rows))
    calls = {
        "candidate_dynamic_segments": 11,
        "candidate_matrix_exponentials": 22,
        "oracle_dynamic_segments": 11,
        "oracle_matrix_exponentials": 22,
        "torch_operations": 0,
        "optimizer_updates": 0,
    }
    result = {
        "identity": args.identity,
        "unique_execution_key": args.key,
        "source_commit": args.source_commit,
        "status": "PASS_BOUNDED_N128_FIRSTCYCLE_ONLY",
        "qualification": False,
        "queries": [
            [value.numerator, value.denominator] for value in candidate_cycle.QUERIES
        ],
        "capsules": capsule_checks,
        "comparison": comparison,
        "candidate": candidate_cost,
        "oracle": oracle_cost,
        "calls": calls,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "remaining_open": [
            "second-cycle packet release after .2",
            "warm/coarse/cold continuation through .36",
            "N256/N512 dynamics",
            "full-network training",
            "finite-domain qualification",
            "asynchronous complete cost",
        ],
        "all_closed": False,
    }
    if (
        candidate_cost["candidate_dynamic_segments"] != 11
        or candidate_cost["candidate_matrix_exponentials"] != 22
    ):
        raise ArithmeticError("candidate cost ledger")
    if (
        oracle_cost["oracle_dynamic_segments"] != 11
        or oracle_cost["oracle_matrix_exponentials"] != 22
    ):
        raise ArithmeticError("oracle cost ledger")
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
