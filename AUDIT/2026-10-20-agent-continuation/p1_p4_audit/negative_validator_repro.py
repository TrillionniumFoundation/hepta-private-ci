"""Synthetic adversarial validation only; never a target-host evidence report.

Imports immutable GitHub source copies without calling the matrix runner,
spawning workers, loading models, making signatures, or writing a qualified
report. Only acceptance/rejection outcomes are persisted.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import platform
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
SOURCES = {
    "2734": "dc271d4f47028e941decce70cc8ef81fb24d2141",
    "2850": "05cf9bb88fc22054ebda949b34d95e908c4ab9de",
}


def load_module(pr: str):
    path = ROOT / "sources" / pr / "scripts/hepta-cell-split-target-matrix.py"
    spec = importlib.util.spec_from_file_location(f"negative_matrix_{pr}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def rebind(module, report: dict) -> None:
    fields = (
        "schema", "authority", "sourceCommit", "workloadDigest",
        "workloadSourceDigest", "host", "cases",
    )
    provisional = {key: report[key] for key in fields}
    if "cellCounts" in report:
        provisional["cellCounts"] = report["cellCounts"]
    observer = {
        "verified": True,
        "observerId": "synthetic-negative-self-assertion-no-independent-signer",
        "sourceCommit": report["sourceCommit"],
        "workloadDigest": report["workloadDigest"],
        "reportDigest": module.digest(provisional),
        "metricsDigest": module.digest([
            {"caseId": case["caseId"], "metricsDigest": case["metricsDigest"]}
            for case in report["cases"]
        ]),
    }
    report["observer"] = observer
    report["reportDigest"] = module.digest({**provisional, "observer": observer})


def synthetic_report(module, pr: str) -> dict:
    # Values are deliberately synthetic; the harness never claims observation.
    metrics = {name: 1 for name in module.REQUIRED_METRICS}
    if hasattr(module, "CELL_COUNTS"):
        metrics.update(gpuObserved=False, gpuMicros=None, gpuBytes=None)
    metrics = module.validate_metrics(metrics)
    workload = hashlib.sha256(b"synthetic negative fixture, never executed").hexdigest()
    cases = [
        {
            **case,
            "status": "measured",  # malicious self-assertion under challenge
            "workloadDigest": workload,
            "metrics": copy.deepcopy(metrics),
            "metricsDigest": module.digest(metrics),
        }
        for case in module.matrix_cases()
    ]
    report = {
        "schema": module.SCHEMA,
        "authority": module.AUTHORITY,
        "sourceCommit": SOURCES[pr],
        "workloadDigest": workload,
        "workloadSourceDigest": workload,
        "host": {"hostId": "synthetic-negative-fixture-never-a-measured-host"},
        "cases": cases,
        "blockingCases": [],
        "status": "qualified",  # untrusted input, never an audit conclusion
    }
    if hasattr(module, "CELL_COUNTS"):
        report["cellCounts"] = list(module.CELL_COUNTS)
    rebind(module, report)
    return report


def run() -> dict:
    results = []
    for pr in SOURCES:
        module, path = load_module(pr)
        baseline = synthetic_report(module, pr)
        variants = {"unsigned_self_asserted_observer": baseline}
        duplicate = copy.deepcopy(baseline)
        duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
        rebind(module, duplicate)
        variants["duplicate_case_after_rebinding"] = duplicate
        wrong_factor = copy.deepcopy(baseline)
        wrong_factor["cases"][0]["encoder_topology"] = "invalid-factor-negative-fixture"
        rebind(module, wrong_factor)
        variants["invalid_factor_after_rebinding"] = wrong_factor
        bad_digest = copy.deepcopy(baseline)
        bad_digest["reportDigest"] = "0" * 64
        variants["incorrect_final_report_digest"] = bad_digest
        body = path.read_bytes()
        blob = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
        for attack, report in variants.items():
            error = None
            try:
                module.validate_report(report)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            accepted = error is None
            expected_accepted = pr == "2734"
            assert accepted == expected_accepted, (pr, attack, error)
            results.append({
                "pr": int(pr), "source_head_sha": SOURCES[pr],
                "source_blob": blob, "source_sha256": hashlib.sha256(body).hexdigest(),
                "attack": attack, "input_case_count": len(report["cases"]),
                "validator_accepted_untrusted_input": accepted,
                "exception": error,
                "expected_observation_matched": True,
            })
    return {
        "classification": "SYNTHETIC_ADVERSARIAL_VALIDATOR_REPRO_ONLY",
        "python": platform.python_version(),
        "production_evidence": False,
        "target_host_workloads_executed": 0,
        "models_loaded": 0,
        "external_signatures_generated": 0,
        "permission_posture": "DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO",
        "results": results,
    }


if __name__ == "__main__":
    output = run()
    (ROOT / "negative_validator_repro_results.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(output, indent=2))
