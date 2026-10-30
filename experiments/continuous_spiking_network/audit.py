"""Independent study inventory audit and conditional paired-seed summaries."""

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import zipfile

import numpy as np
from scipy.stats import t as student_t

from .audit_checks import (
    AuditError as AuditError,
    TOLERANCE as TOLERANCE,
    _inside,
    _json,
    _require,
    _sha,
    classification_metrics as classification_metrics,
    verify_boundary as verify_boundary,
    verify_checkpoint as verify_checkpoint,
    verify_classification as verify_classification,
)


CONFIG_FIELDS = (
    "stage",
    "task",
    "width",
    "depth",
    "train_size",
    "length",
    "updates",
    "batch_size",
    "lr",
    "data_seed",
    "val_size",
    "test_size",
)
UNCERTAINTY_SCOPE = (
    "Paired t intervals describe training-seed randomness conditional on the frozen "
    "held-out sources and data construction. They do not estimate new-source, "
    "new-speaker or population generalization uncertainty. Accuracy is primary; "
    "cross-entropy is secondary. No winner is assigned by this audit."
)


def verify_source(source_dir, results):
    source_dir, results = Path(source_dir), Path(results)
    seal_path = results / "SOURCE_SEAL.json"
    if not seal_path.exists():
        seal_path = source_dir / "SOURCE_SEAL.json"
    seal = _json(seal_path)
    records = {}
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [name for name in dirs if name not in {"results", "__pycache__"}]
        for name in files:
            path = Path(root) / name
            if path.suffix == ".py" or name in {"PROTOCOL.json", "requirements.txt"}:
                records[str(path.relative_to(source_dir))] = _sha(path)
    digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    _require(
        records == seal["files"] and digest == seal["sha256"],
        "Scientific source differs from frozen seal.",
    )
    return seal, _json(source_dir / "PROTOCOL.json")


def paired_interval(values, confidence=0.95):
    values = np.asarray(values, dtype=float)
    _require(
        len(values) > 0 and np.isfinite(values).all(), "Invalid paired differences."
    )
    mean = float(values.mean())
    if len(values) < 2:
        return {
            "confidence": confidence,
            "mean": mean,
            "lower": None,
            "upper": None,
            "n": len(values),
            "reason": "At least two independent training seeds are needed.",
        }
    margin = float(
        student_t.ppf((1 + confidence) / 2, len(values) - 1)
        * values.std(ddof=1)
        / math.sqrt(len(values))
    )
    return {
        "confidence": confidence,
        "mean": mean,
        "lower": mean - margin,
        "upper": mean + margin,
        "n": len(values),
    }


def aggregate_runs(valid_runs):
    grouped, comparisons = defaultdict(list), defaultdict(lambda: defaultdict(dict))
    for run in valid_runs:
        if run["kind"] != "classification":
            continue
        spec = run["spec"]
        config = {key: spec.get(key) for key in CONFIG_FIELDS}
        key = json.dumps(config, sort_keys=True)
        architecture = spec["architecture"]
        grouped[(key, architecture)].append(run)
        _require(
            spec["seed"] not in comparisons[key][architecture],
            "Duplicate seed within an aggregation configuration.",
        )
        comparisons[key][architecture][spec["seed"]] = run
    aggregates = []
    for (key, architecture), runs in sorted(grouped.items()):
        summary = dict(
            json.loads(key),
            architecture=architecture,
            seeds=sorted(run["spec"]["seed"] for run in runs),
            runs=len(runs),
        )
        summary["mean"] = {
            metric: float(np.mean([run["audit"]["metrics"][metric] for run in runs]))
            for metric in ("accuracy", "cross_entropy", "brier")
        }
        summary["mean"].update(
            {
                key: float(np.mean([run["result"][key] for run in runs]))
                for key in ("training_cpu_seconds", "total_cpu_seconds")
            }
        )
        summary["mean"]["parameters"] = {
            key: float(np.mean([run["result"]["parameters"][key] for run in runs]))
            for key in ("total", "frontend", "backbone", "readout")
        }
        aggregates.append(summary)
    contrasts = []
    for key, architectures in sorted(comparisons.items()):
        if "hcsn" not in architectures:
            continue
        config = json.loads(key)
        for other in sorted(set(architectures) - {"hcsn"}):
            seeds = sorted(set(architectures["hcsn"]) & set(architectures[other]))
            if not seeds:
                continue
            pair = [
                (architectures["hcsn"][seed], architectures[other][seed])
                for seed in seeds
            ]
            _require(
                all(
                    a["audit"]["heldout_fingerprint"]
                    == b["audit"]["heldout_fingerprint"]
                    and a["audit"]["batch_fingerprint"]
                    == b["audit"]["batch_fingerprint"]
                    for a, b in pair
                ),
                "Attempted paired contrast with unmatched heldout sources or minibatches.",
            )
            row = dict(
                config,
                contrast=f"hcsn-minus-{other}",
                paired_seeds=seeds,
                n_pairs=len(seeds),
                metrics={},
            )
            for metric in ("accuracy", "cross_entropy"):
                values = [
                    a["audit"]["metrics"][metric] - b["audit"]["metrics"][metric]
                    for a, b in pair
                ]
                estimates = {"differences": values, "ci95": paired_interval(values)}
                if config["stage"] == "mechanism":
                    estimates["bonferroni_four_comparisons_ci9875"] = paired_interval(
                        values, 0.9875
                    )
                    estimates["formal_five_seed_complete"] = len(seeds) == 5
                row["metrics"][metric] = estimates
            contrasts.append(row)
    return aggregates, contrasts


def audit_results(results, source_dir=None):
    results = Path(results).resolve()
    source_dir = Path(source_dir) if source_dir is not None else Path(__file__).parent
    report = {
        "schema": "hcsn-study-audit-v1",
        "issues": [],
        "runs": [],
        "failures": [],
        "uncertainty_scope": UNCERTAINTY_SCOPE,
    }

    def issue(code, message, run_id=None, severity="error"):
        report["issues"].append(
            {
                "code": code,
                "message": str(message),
                "run_id": run_id,
                "severity": severity,
            }
        )

    expected_seal, protocol = None, {}
    try:
        seal, protocol = verify_source(source_dir, results)
        expected_seal = seal["sha256"]
        report["source_seal"] = expected_seal
    except (OSError, ValueError, KeyError) as error:
        issue("source_seal", error)
    planned = {}
    try:
        inventory = _json(results / "RUNS.json")
        _require(
            inventory["source_seal"] == expected_seal,
            "RUNS source seal differs from frozen source.",
        )
        digest = hashlib.sha256(
            json.dumps(
                inventory["runs"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        _require(
            digest == protocol["runs_sha256"],
            "Run list differs from sealed preregistration digest.",
        )
        for run in inventory["runs"]:
            _inside(results, run["run_id"])
            _require(run["run_id"] not in planned, "Duplicate preregistered run ID.")
            planned[run["run_id"]] = run["spec"]
        report["runs_sha256"] = digest
    except (OSError, ValueError, KeyError) as error:
        issue("inventory", error)
    actual = {
        str(path.parent.relative_to(results)): path
        for path in sorted(results.rglob("RESULT.json"))
    }
    report["inventory"] = {
        "planned": len(planned),
        "completed": len(actual),
        "missing": sorted(set(planned) - set(actual)),
        "unexpected": sorted(set(actual) - set(planned)),
    }
    for run_id in report["inventory"]["unexpected"]:
        issue("unplanned_result", "Completed result has no frozen plan entry.", run_id)
    valid = []
    for run_id, path in actual.items():
        try:
            result = _json(path)
            _require(
                result["source_seal"] == expected_seal,
                "Run source seal differs from frozen source.",
            )
            boundary = result.get("kind") == "boundary_study"
            spec = (
                {"stage": "boundary", "seed": result["seed"]}
                if boundary
                else result["spec"]
            )
            _require(
                run_id in planned and spec == planned[run_id],
                "Completed spec differs from preregistered spec.",
            )
            audit = (
                verify_boundary(path.parent, result)
                if boundary
                else verify_classification(path.parent, result)
            )
            run = {
                "run_id": run_id,
                "kind": "boundary" if boundary else "classification",
                "spec": spec,
                "status": "verified",
                "audit": audit,
            }
            report["runs"].append(run)
            valid.append(dict(run, result=result))
        except (
            OSError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            zipfile.BadZipFile,
            EOFError,
        ) as error:
            issue("run_artifact", error, run_id)
            report["runs"].append(
                {"run_id": run_id, "status": "invalid", "error": str(error)}
            )
    for path in sorted(results.rglob("FAILED.json")):
        run_id = str(path.parent.relative_to(results))
        try:
            details = _json(path)
        except (OSError, ValueError) as error:
            details = {"unreadable_failure_record": str(error)}
        recovered = any(
            run["run_id"] == run_id and run["status"] == "verified"
            for run in report["runs"]
        )
        report["failures"].append(
            {
                "run_id": run_id,
                "file": str(path.relative_to(results)),
                "recovered": recovered,
                "details": details,
            }
        )
        issue(
            "retained_failure",
            "Failure record retained; inspect attempt history.",
            run_id,
            "warning" if recovered else "error",
        )
    try:
        report["aggregates"], report["paired_contrasts"] = aggregate_runs(valid)
    except (ValueError, KeyError) as error:
        issue("aggregation", error)
        report["aggregates"], report["paired_contrasts"] = [], []
    if any(item["severity"] == "error" for item in report["issues"]):
        report["status"] = "failed"
    elif report["inventory"]["missing"]:
        report["status"] = "incomplete"
    else:
        report["status"] = (
            "passed_with_recovered_failures" if report["failures"] else "passed"
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit_results(args.results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "inventory": report["inventory"],
                "issues": len(report["issues"]),
            }
        )
    )
    raise SystemExit(0 if report["status"].startswith("passed") else 1)


if __name__ == "__main__":
    main()
