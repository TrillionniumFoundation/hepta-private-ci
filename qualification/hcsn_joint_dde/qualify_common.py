"""Rerun state recovery and the original retained domain on one frozen source."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    if any(
        os.environ.get(key) != "1"
        for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
    ):
        raise ValueError("one declared numerical thread is required")
    root = Path(__file__).resolve().parents[2]
    module = Path(__file__).parent
    paths = sorted(module.glob("*.py")) + [
        module / "GRADED_PROTOCOL.json",
        module / "COMMON_SOURCE_PROTOCOL.json",
        root / "qualification/hcsn_boundary_audit/spatial_generator.py",
        root / "qualification/hcsn_boundary_audit/refractory_transport.py",
    ]

    def identities():
        return {str(p.relative_to(root)): digest(p) for p in paths}

    before = identities()
    args.output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    executions = []
    commands = [
        (
            "STATE",
            [
                sys.executable,
                "-B",
                "-m",
                "qualification.hcsn_joint_dde.qualify_state",
                "--output",
                str(args.output / "state"),
            ],
        ),
        (
            "DOMAIN",
            [
                sys.executable,
                "-B",
                "-m",
                "qualification.hcsn_joint_dde.audit_graded",
                "--input-root",
                str(args.input_root),
                "--output-dir",
                str(args.output / "domain"),
            ],
        ),
    ]
    (args.output / "SOURCE_BEFORE.json").write_text(json.dumps(before, indent=2) + "\n")
    for name, command in commands:
        begin = time.perf_counter()
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        with (
            (args.output / f"{name}.stdout").open("wb") as stdout,
            (args.output / f"{name}.stderr").open("wb") as stderr,
        ):
            completed = subprocess.run(
                command, stdout=stdout, stderr=stderr, timeout=1800, cwd=root
            )
        after_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        record = {
            "lane": name,
            "command": command,
            "returncode": completed.returncode,
            "wall_seconds": time.perf_counter() - begin,
            "user_cpu_seconds": after_usage.ru_utime - usage.ru_utime,
            "system_cpu_seconds": after_usage.ru_stime - usage.ru_stime,
            "maximum_child_rss_kib": after_usage.ru_maxrss,
        }
        executions.append(record)
        (args.output / "EXECUTIONS.json").write_text(
            json.dumps(executions, indent=2) + "\n"
        )
        print(json.dumps(record), flush=True)
        if completed.returncode:
            raise RuntimeError(
                f"{name} failed; retained original outputs remain in {args.output}"
            )
    state = json.loads((args.output / "state/RESULT.json").read_text())
    domain = json.loads((args.output / "domain/SUMMARY.json").read_text())
    after = identities()
    if before != after:
        raise RuntimeError("common-source mutation")
    for relative, sha256 in state["source_before"].items():
        if before[relative] != sha256 or state["source_after"][relative] != sha256:
            raise RuntimeError("state lane source mismatch")
    for absolute, sha256 in domain["source_before"].items():
        relative = str(Path(absolute).relative_to(root))
        if before[relative] != sha256 or domain["source_after"][absolute] != sha256:
            raise RuntimeError("domain lane source mismatch")
    passed = (
        state["tests_passed"] == 28
        and state["skipped"] == 0
        and state["cold_process_restore"]
        and state["resume_clock"] == 0.417
        and domain["engineering_checks_passed"]
        and domain["direct_DDE_executions"] == 30
        and len(domain["reports"]) == 2
        and all(
            r["positions"] == 14336 and r["continuation_failures_at_original_1pct"] == 0
            for r in domain["reports"]
        )
    )
    result = {
        "schema": "hcsn-common-source-reexecution-v1",
        "status": "HOLD_NO_GO",
        "engineering_checks_passed": passed,
        "execution_source_commit": args.source_commit,
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "source_before": before,
        "source_after": after,
        "executions": executions,
        "tests_passed": state["tests_passed"],
        "skipped": state["skipped"],
        "cold_process_restore": state["cold_process_restore"],
        "resume_clock": state["resume_clock"],
        "cold_maximum_absolute_error": max(state["maximum_absolute_errors"].values()),
        "domain_reports": domain["reports"],
        "direct_DDE_executions": domain["direct_DDE_executions"],
        "max_spectral_DDE_error": domain["max_spectral_DDE_error"],
        "all_positions_evaluation": "linear first-excursion kernel; not 14336 separate DDE trajectories",
        "persistent_recovery_scope": "28 source tests and the declared fresh-process fixture; not all retained laws",
        "optimizer_calls": 0,
        "complete_c2_replays": 0,
        "independent_future_tasks": 0,
        "prior_results_pooled": False,
        "cell_adoption": False,
        "raw_output_sha256": {
            str(p.relative_to(args.output)): digest(p)
            for p in sorted(args.output.rglob("*"))
            if p.is_file()
        },
    }
    (args.output / "RESULT.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "engineering_checks_passed",
                    "tests_passed",
                    "skipped",
                    "cold_maximum_absolute_error",
                    "direct_DDE_executions",
                    "max_spectral_DDE_error",
                )
            }
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
