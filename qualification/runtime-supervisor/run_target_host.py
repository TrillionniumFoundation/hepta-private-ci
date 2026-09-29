#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import platform
import subprocess
import time

from verify_receipt import REQUIRED_SCENARIOS, verify


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_case(case: dict, inherited_env: dict[str, str]) -> dict:
    name = case["name"]
    argv = case["argv"]
    timeout_seconds = int(case.get("timeout_seconds", 300))
    env = inherited_env.copy()
    env.update({str(key): str(value) for key, value in case.get("env", {}).items()})
    started = time.monotonic()
    completed = subprocess.run(
        argv,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    elapsed = round((time.monotonic() - started) * 1000)
    evidence = {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
    }
    return {
        "name": name,
        "passed": completed.returncode == 0,
        "elapsed_millis": elapsed,
        "evidence": evidence,
        "final_operator_outcome": case.get(
            "final_operator_outcome",
            "scenario command returned its bounded terminal result",
        ),
    }


def metric_projection(snapshot: dict) -> dict:
    projected = {}
    for lock_class in ("tick", "read", "mutation"):
        item = snapshot[lock_class]
        projected[lock_class] = {
            "wait_p50_nanos": item["wait"]["p50_upper_bound_nanos"],
            "wait_p95_nanos": item["wait"]["p95_upper_bound_nanos"],
            "wait_p99_nanos": item["wait"]["p99_upper_bound_nanos"],
            "wait_max_nanos": item["wait"]["max_nanos"],
            "hold_p50_nanos": item["hold"]["p50_upper_bound_nanos"],
            "hold_p95_nanos": item["hold"]["p95_upper_bound_nanos"],
            "hold_p99_nanos": item["hold"]["p99_upper_bound_nanos"],
            "hold_max_nanos": item["hold"]["max_nanos"],
        }
    return projected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--lock-metrics", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plan = json.loads(pathlib.Path(args.plan).read_text(encoding="utf-8"))
    cases = plan.get("scenarios", [])
    names = {case.get("name") for case in cases}
    missing = REQUIRED_SCENARIOS - names
    extra = names - REQUIRED_SCENARIOS
    if missing or extra:
        raise SystemExit(
            f"qualification plan mismatch: missing={sorted(missing)} extra={sorted(extra)}"
        )

    inherited_env = os.environ.copy()
    results = [run_case(case, inherited_env) for case in cases]
    metrics = json.loads(pathlib.Path(args.lock_metrics).read_text(encoding="utf-8"))
    binary = pathlib.Path(args.binary)
    receipt = {
        "schema": "hepta.runtime-supervisor-qualification.v1",
        "source_commit": args.source_commit,
        "binary_sha256": sha256_file(binary),
        "host": {
            "identity": platform.node(),
            "os": platform.system(),
            "kernel": platform.release(),
            "runtime": platform.python_version(),
        },
        "lock_metrics": metric_projection(metrics),
        "scenarios": results,
    }
    verify(receipt)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
