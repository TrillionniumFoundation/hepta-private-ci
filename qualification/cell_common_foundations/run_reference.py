"""Run bounded common-foundation references and retain exact-source evidence.

Run from the repository root. The output is create-only. Synthetic mechanism
execution is separate from real-task, energy, native-owner and adoption gates.
"""

import argparse
from dataclasses import asdict
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest

import numpy as np

from .protocol import (
    AttemptSpec,
    canonical_digest,
    compare_profiles,
    cost_observation,
    source_inventory,
    summarize_attempts,
)


BASE_COMMIT = "bb048cb811c2b755b7e54e97d24c63ec7ec8d1b7"
MAIN_COMMIT = "732e934ba496d90fbe042b8d41d479ef901643e5"
SEEDS = (11, 29, 47)
PLAN = {
    "schema": "hepta.cell-common-reference-plan.v1",
    "main_ancestor": MAIN_COMMIT,
    "hcsn_parent": BASE_COMMIT,
    "seeds": SEEDS,
    "credit": {
        "updates": 12,
        "horizon": 12,
        "feedback_time": "terminal_only",
        "tuning_trials": 0,
    },
    "temporal": {
        "horizon": 32,
        "size": 24,
        "head_steps": 40,
        "training_scope": "frozen_kernels_head_only",
        "tuning_trials": 0,
    },
    "plasticity": {"steps_per_task": 24, "tasks": 3, "tuning_trials": 0},
    "threads": 1,
    "scope": "synthetic_mechanism_reference",
    "confirmation_data_consumed": False,
    "real_task_efficacy_claim": False,
}


class RecordedTests(unittest.TextTestResult):
    """Retain actual executed names as well as errors and skips."""

    def startTest(self, test):
        if not hasattr(self, "executed_names"):
            self.executed_names = []
        self.executed_names.append(test.id())
        super().startTest(test)


def _inventory(root):
    paths = []
    for directory in ("cell_common_foundations", "hcsn_differentiable"):
        paths.extend(
            path.relative_to(root).as_posix()
            for path in (root / "qualification" / directory).rglob("*.py")
        )
    return source_inventory(root, paths)


def _roster():
    from .credit import METHODS, credit_attempt_spec
    from .plasticity import PLASTICITY_METHODS

    specs = []
    for seed in SEEDS:
        for location in ("all", "sparse"):
            for method in METHODS:
                declared = credit_attempt_spec(
                    seed,
                    method,
                    location,
                    PLAN["credit"]["updates"],
                    PLAN["credit"]["horizon"],
                    include_causal_probe=seed == SEEDS[0],
                )
                specs.append(
                    AttemptSpec(
                        **{
                            key: declared[key]
                            for key in ("attempt_id", "family", "method", "seed")
                        }
                    )
                )
        for kind in ("gru", "diagonal_ssm", "hcsn", "lif_event"):
            specs.append(AttemptSpec(f"temporal-{seed}-{kind}", "temporal", kind, seed))
        for method in PLASTICITY_METHODS:
            specs.append(
                AttemptSpec(f"plasticity-{seed}-{method}", "plasticity", method, seed)
            )
    return specs


def _write_new(path, value):
    encoded = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        import os

        os.fsync(stream.fileno())


def _credit_panel(on_attempt):
    from .credit import METHODS, credit_attempt_spec, run_credit_attempt

    attempts, comparisons, reference_profiles = [], [], {}
    for seed in SEEDS:
        for location in ("all", "sparse"):
            for method in METHODS:
                spec = credit_attempt_spec(
                    seed,
                    method,
                    location,
                    PLAN["credit"]["updates"],
                    PLAN["credit"]["horizon"],
                    include_causal_probe=seed == SEEDS[0],
                )
                on_attempt("started", {**spec, "status": "running"})
                record = run_credit_attempt(
                    seed,
                    method,
                    location,
                    PLAN["credit"]["updates"],
                    PLAN["credit"]["horizon"],
                    include_causal_probe=seed == SEEDS[0],
                )
                on_attempt("finished", record)
                attempts.append(record)
                if record["status"] == "completed":
                    profile = record["comparison_profile"]
                    group = (seed, location)
                    reference = reference_profiles.setdefault(group, profile)
                    comparisons.append(
                        {
                            "seed": seed,
                            "feedback_locations": location,
                            "method": method,
                            **compare_profiles(reference, profile),
                        }
                    )
    return {
        "schema": "hepta.cell-credit-attempt-panel.v1",
        "attempts": attempts,
        "feedback_time": "terminal_only",
        "feedback_locations": ["all", "sparse"],
        "matched_profile_checks": comparisons,
        "comparison_contract_passed": (
            len(comparisons) == len(SEEDS) * 2 * len(METHODS)
            and all(row["matched"] for row in comparisons)
        ),
        "scope": "fp64_tanh_reference",
        "production_adoption": "not_granted",
    }


def _temporal_records(report):
    rows = []
    for attempt in report["attempts"]:
        status = attempt["status"]
        reason = None
        if status in {"failed", "cancelled"}:
            reason = f"{attempt.get('error_type', 'UnknownError')}: {attempt.get('error') or '<no message>'}"
        rows.append(
            {
                "attempt_id": f"temporal-{attempt['seed']}-{attempt['kernel']}",
                "family": "temporal",
                "method": attempt["kernel"],
                "seed": attempt["seed"],
                "status": status,
                "reason": reason,
                "result": attempt,
                "actual_updates": attempt["head_updates_completed"],
                "planned_updates": 3 * PLAN["temporal"]["head_steps"],
            }
        )
    return rows


def run_reference(output_path=None):
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    root = Path(__file__).resolve().parents[2]
    before = _inventory(root)
    roster = _roster()
    components, sections, family_errors = {}, {}, {}
    observed = {}
    planned = {spec.attempt_id: spec for spec in roster}
    attempt_directory = None
    if output_path is not None:
        output_path = Path(output_path)
        plan_path = output_path.with_suffix(".plan.json")
        attempt_directory = output_path.with_suffix(".attempts")
        if output_path.exists() or plan_path.exists() or attempt_directory.exists():
            raise ValueError(
                "attempt already exists; never replay under its old output identity"
            )
        _write_new(
            plan_path,
            {
                "plan": PLAN,
                "plan_digest": canonical_digest(PLAN),
                "source": before,
                "roster": [asdict(spec) for spec in roster],
            },
        )
        attempt_directory.mkdir()

    def observe(kind, record):
        if "kernel" in record:
            record = _temporal_records({"attempts": [record]})[0]
        key = record["attempt_id"]
        if key not in planned or any(
            record[field] != getattr(planned[key], field)
            for field in ("family", "method", "seed")
        ):
            raise ValueError("attempt differs from the persisted roster")
        if kind not in {"started", "finished"}:
            raise ValueError("invalid attempt observation")
        previous = observed.get(key)
        if (kind == "started" and previous is not None) or (
            kind == "finished" and (previous is None or previous["status"] != "running")
        ):
            raise ValueError("duplicate or unordered attempt observation")
        canonical_digest(record)
        if attempt_directory is not None:
            filename = canonical_digest(key) + "." + kind + ".json"
            _write_new(
                attempt_directory / filename,
                {
                    "event": kind,
                    "elapsed_seconds": time.perf_counter() - start_wall,
                    "record": record,
                },
            )
        observed[key] = record

    torch_version = None
    try:
        import torch

        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch_version = torch.__version__
    except ImportError:
        pass

    test_log = io.StringIO()
    test_start = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        [
            f"qualification.cell_common_foundations.test_{name}"
            for name in ("protocol", "credit", "plasticity", "temporal", "runner")
        ]
    )
    result = unittest.TextTestRunner(
        stream=test_log, verbosity=2, resultclass=RecordedTests
    ).run(suite)
    components["tests"] = time.perf_counter() - test_start
    test_report = {
        "tests_run": result.testsRun,
        "failures": [
            {"name": case.id(), "traceback": error} for case, error in result.failures
        ],
        "errors": [
            {"name": case.id(), "traceback": error} for case, error in result.errors
        ],
        "skipped": [
            {"name": case.id(), "reason": reason} for case, reason in result.skipped
        ],
        "executed_names": getattr(result, "executed_names", []),
        "successful": result.testsRun > 0
        and result.wasSuccessful()
        and not result.skipped,
        "scope": "mechanism_and_contract_tests_including_small_test_only_training_fixtures",
    }

    for family in ("credit", "plasticity", "temporal"):
        family_start = time.perf_counter()
        try:
            if family == "credit":
                panel = _credit_panel(observe)
            elif family == "plasticity":
                from .plasticity import run_plasticity_pilot

                panel = run_plasticity_pilot(
                    SEEDS,
                    steps_per_task=PLAN["plasticity"]["steps_per_task"],
                    on_attempt=observe,
                )
            else:
                from .temporal import run_temporal_pilot

                panel = run_temporal_pilot(
                    SEEDS,
                    horizon=PLAN["temporal"]["horizon"],
                    size=PLAN["temporal"]["size"],
                    head_steps=PLAN["temporal"]["head_steps"],
                    on_attempt=observe,
                )
            canonical_digest(panel)
            sections[family] = panel
        except Exception as error:
            family_errors[family] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            # Admission/import failures leave planned attempts unstarted; they
            # do not fabricate an attempted fit or erase the other families.
        components[family] = time.perf_counter() - family_start

    after = _inventory(root)
    unchanged = before == after
    summary = summarize_attempts(roster, list(observed.values()))
    peak_rss = None
    try:
        import resource

        rss_high_water = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_rss = int(
            rss_high_water if platform.system() == "Darwin" else rss_high_water * 1024
        )
    except (ImportError, AttributeError):
        pass
    cost = cost_observation(
        wall_seconds=time.perf_counter() - start_wall,
        cpu_seconds=time.process_time() - start_cpu,
        peak_rss_bytes=peak_rss,
        components=components,
    )
    cost["measurement_window"] = (
        "inside run_reference; includes tests, all panels and attempt-file writes; "
        "excludes interpreter startup, dependency setup and final report serialization"
    )
    comparison_passed = sections.get("credit", {}).get(
        "comparison_contract_passed", False
    )
    complete = (
        summary["complete"]
        and test_report["successful"]
        and comparison_passed
        and unchanged
        and not family_errors
    )
    return {
        "schema": "hepta.cell-common-reference-result.v1",
        "status": "REFERENCE_EXECUTION_COMPLETED"
        if complete
        else "REFERENCE_EXECUTION_INCOMPLETE",
        "scientific_acceptance": "HOLD",
        "production_adoption": "not_granted",
        "plan": PLAN,
        "plan_digest": canonical_digest(PLAN),
        "source": before,
        "source_unchanged": unchanged,
        "runtime": {
            "python": sys.version,
            "numpy": np.__version__,
            "torch": torch_version,
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "roster": [asdict(spec) for spec in roster],
        "attempt_records": list(observed.values()),
        "attempt_summary": summary,
        "tests": test_report,
        "family_errors": family_errors,
        "panels": sections,
        "cost": cost,
        "unclosed_gates": [
            "independently sourced real terminal tasks and retention panels",
            "native learning/artifact owner consumption and reversible adoption",
            "full-parameter temporal training and equal tuning opportunities",
            "same-hardware isolated peak memory and measured end-to-end energy",
            "optimal reset/renewal and declared HCSN numerical-domain qualification",
            "measured structural migration/relearning and fixed-graph net benefit",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new JSON output path; existing results are never overwritten",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; preserve the original attempt")
    report = run_reference(args.output)
    _write_new(args.output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output),
                "attempts": report["attempt_summary"],
                "tests_run": report["tests"]["tests_run"],
                "source_digest": report["source"]["digest"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "REFERENCE_EXECUTION_COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
