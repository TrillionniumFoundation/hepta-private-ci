"""Freeze native coverage before model execution; independently validate all shards."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from benchmark_coverage import aggregate, decode_plan, plan_coverage
from native import digest, load
from run_native import execution_binding
from tensor_contract import bounded_read, strict_json


def write_exclusive(path: Path, value: dict):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def preregister(staged: Path, output: Path, kind: str, *, folds: int, shards: int, limit: int | None):
    # Inventory creation hashes files; it does not instantiate or train a model.
    from pretrained import file_inventory

    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("preregistration requires the exact tested source commit")
    staging = strict_json(bounded_read(staged / "staging.json", 1024 * 1024))
    benchmark = load(staged / f"{kind}.json", kind, staging[kind]["sha256"],
                     allow_unresolved_evidence=True, session_conflicts="retain-versioned",
                     invalid_history="quarantine-question")
    plan = plan_coverage(benchmark, folds=folds, shards=shards, per_fold_limit=limit)
    value = {"schema": "hepta.memory-benchmark.preregistered.v1", "coverage": plan.content(),
             "execution_binding": execution_binding(digest(file_inventory(staged / "reader")),
                                                     digest(file_inventory(staged / "encoder")), "pretrained-offline")}
    write_exclusive(output, value)
    return value


def collect(plan_path: Path, receipts_root: Path, output: Path):
    declared = strict_json(bounded_read(plan_path, 32 * 1024 * 1024))
    if set(declared) != {"schema", "coverage", "execution_binding"} or declared["schema"] != "hepta.memory-benchmark.preregistered.v1":
        raise ValueError("unknown preregistration")
    plan = decode_plan(declared["coverage"])
    paths = sorted(receipts_root.rglob("report.json"))
    if len(paths) != plan.folds * plan.shards:
        raise ValueError("missing or duplicate shard artifact; complete report unavailable")
    receipts = [strict_json(bounded_read(path, 32 * 1024 * 1024)) for path in paths]
    result = aggregate(plan, receipts, execution_binding=declared["execution_binding"])
    write_exclusive(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="operation", required=True)
    build = commands.add_parser("plan")
    build.add_argument("staged", type=Path)
    build.add_argument("output", type=Path)
    build.add_argument("kind", choices=("locomo", "longmemeval"))
    build.add_argument("--folds", type=int, default=1)
    build.add_argument("--shards", type=int, default=1)
    build.add_argument("--limit", type=int)
    read = commands.add_parser("collect")
    read.add_argument("plan", type=Path)
    read.add_argument("receipts", type=Path)
    read.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.operation == "plan":
        preregister(args.staged, args.output, args.kind, folds=args.folds, shards=args.shards, limit=args.limit)
    else:
        result = collect(args.plan, args.receipts, args.output)
        if any(arm["failed"] for arm in result["arms"].values()):
            raise SystemExit("complete coverage includes failed model work; failure counts are retained, not waived")
