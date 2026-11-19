"""Bind the completed recovery evidence without altering scientific results."""

from collections import Counter
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
E = ROOT / "research_evidence/hepta_stable_flow_20261029"
R = E / "recovery_20261030"
FORMAL = E / "formal_run001"
FINAL = R / "final_recovery_audit.json"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def bound(path, expected, size=None):
    require(path.resolve().is_relative_to(ROOT), "Binding escapes repository")
    require(path.is_file() and not path.is_symlink(), "Missing file: " + str(path))
    require(digest(path) == expected, "Hash mismatch: " + str(path))
    require(size is None or path.stat().st_size == size, "Size mismatch: " + str(path))


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        stream.write("\n")


def main():
    require(not FINAL.exists(), "Final audit is immutable; preserve prior attempts")
    protocol = read(FORMAL / "protocol.json")
    bound(
        FORMAL / "protocol.json", read(FORMAL / "freeze_seal.json")["protocol_sha256"]
    )
    require(len(protocol["source_sha256"]) == 11, "Frozen core coverage changed")
    for name, expected in protocol["source_sha256"].items():
        bound(ROOT / "experiments/call_put_stable_flow" / name, expected)
        bound(FORMAL / "source_snapshot" / name, expected)
    splits = read(FORMAL / "data_manifest.json")["splits"]
    require(len(splits) == 6, "Raw split coverage changed")
    for name, record in splits.items():
        bound(FORMAL / "data" / (name + ".npz"), record["file_sha256"])
    completions = read(FORMAL / "all_training_complete_seal.json")["complete_sha256"]
    require(
        len(completions) == len(protocol["candidates"]) == 60, "Candidate count changed"
    )
    checkpoint_count = 0
    for identifier, expected in completions.items():
        folder = FORMAL / "candidates" / identifier
        bound(folder / "complete.json", expected)
        receipt = read(folder / "complete.json")
        require(receipt["status"] == "complete", "Training was not complete")
        for row in receipt["checkpoints"].values():
            bound(folder / row["file"], row["sha256"])
            checkpoint_count += 1
    require(checkpoint_count == 300, "Weight coverage changed")
    bound(
        FORMAL / "selection.json",
        read(FORMAL / "selection_seal.json")["selection_sha256"],
    )
    selected = read(FORMAL / "selection.json")["selected"]
    identities = {(r["task"], r["arm"], r["seed"], r["regime"]) for r in selected}
    require(len(selected) == len(identities) == 60, "Selection identities changed")
    primary = read(R / "primary_reconstruction_receipt.json")
    require(
        primary["all_original_primary_digests_reproduced"]
        and primary["original_inputs_unchanged"]
        and not primary["training_or_selection_executed"],
        "Primary reconstruction failed",
    )
    require(len(primary["comparisons"]) == 61, "Primary artifact coverage changed")
    for row in primary["comparisons"]:
        require(row["exact_match"], "A primary file differs from the original")
        bound(ROOT / row["path"], row["sha256"], row["bytes"])
    measurement = read(R / "replayed_measurements_audit.json")
    require(
        measurement["status"] == "complete"
        and measurement["artifact_integrity_passed"]
        and measurement["mismatch_count"] == 0,
        "Independent measurement audit failed",
    )
    for row in measurement["bound_inputs"]:
        bound(ROOT / row["path"], row["sha256"], row.get("bytes"))
    require(
        measurement["primary_improvement_gates_passed"] == 0
        and measurement["primary_improvement_gates_total"] == 24,
        "Scientific conclusion changed",
    )
    old_report = read(E / "report002/report_receipt.json")
    bound(
        E / "report002/report_receipt.json",
        "e531f9be028d52a20e9c92e987557c70b8bb4c7ed2cabd3426bb7462a2436c8a",
    )
    availability = []
    for row in old_report["consumed_inputs"]:
        path = ROOT / row["path"]
        status = "missing"
        if path.is_file():
            bound(path, row["sha256"], row["bytes"])
            status = "exact"
        availability.append({**row, "status": status})
    counts = dict(Counter(row["status"] for row in availability))
    require(counts == {"exact": 700, "missing": 34}, "Unexpected original availability")
    availability_path = R / "original_input_availability_final.json"
    write_new(
        availability_path,
        {
            "schema": "hepta-original-report-input-availability-v1",
            "created_utc": datetime.now(UTC).isoformat(),
            "basis_report_receipt_sha256": digest(E / "report002/report_receipt.json"),
            "counts": counts,
            "original_archive_recovered": False,
            "missing_files_are_not_replaced_with_new_clock_records": True,
            "files": availability,
        },
    )
    for row in old_report["outputs"]:
        path = E / "report002" / row["path"]
        if path.is_file():
            bound(path, row["sha256"], row["bytes"])
        else:
            require(
                row["path"] == "report_summary.json", "Unexpected original report loss"
            )
    report_path = E / "report003_recovery/report_receipt.json"
    report = read(report_path)
    for row in report["consumed_inputs"]:
        bound(ROOT / row["path"], row["sha256"], row["bytes"])
    for row in report["outputs"]:
        bound(report_path.parent / row["path"], row["sha256"], row["bytes"])
    qa = read(R / "report003_artifact_qa.json")
    require(
        qa["artifact_integrity_passed"]
        and qa["html_rerender_from_saved_summary_and_images_byte_exact"],
        "Recovery report QA incomplete",
    )
    bound(report_path, qa["report_receipt_sha256"])
    require(
        len(report["consumed_inputs"]) == 754 and len(report["outputs"]) == 7,
        "Recovery report scope changed",
    )
    numerical = read(E / "trained_numerics_replay_20261030/execution/summary.json")
    e2e = Counter(row["end_to_end"]["status"] for row in numerical["records"])
    dop = Counter(
        row["independent_flow"]["status"]
        for row in numerical["records"]
        if "independent_flow" in row
    )
    require(
        e2e == {"passed": 24}
        and dop == {"passed": 7, "failed": 1}
        and numerical["execution_errors"] == 0,
        "Numerical flags changed",
    )
    raw_old = [
        r
        for r in old_report["consumed_inputs"]
        if "/trained_numerics_appendix001/execution/" in r["path"]
        and r["path"].endswith(".npz")
    ]
    require(len(raw_old) == 104, "Original numerical raw coverage changed")
    for row in raw_old:
        bound(ROOT / row["path"], row["sha256"], row["bytes"])
    fixture = read(R / "archive_tests/fixture_verification_receipt.json")
    require(
        fixture["returncode"] == 0 and fixture["tests"] == 6,
        "Archive format fixtures failed",
    )
    spec = importlib.util.spec_from_file_location(
        "recovery_archive", R / "recovery_archive.py"
    )
    archive = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archive)
    artifacts = archive.inventory(ROOT)
    require(
        not any(row["path"] == str(FINAL.relative_to(ROOT)) for row in artifacts),
        "Recursive final audit binding",
    )
    result = {
        "schema": "hepta-final-recovery-audit-v1",
        "created_utc": datetime.now(UTC).isoformat(),
        "status": "complete",
        "artifact_integrity_passed": True,
        "all_research_blockers_closed": False,
        "all_registered_scientific_gates_passed": False,
        "original_archive_recovered": False,
        "prior_historical_commit_recovered": False,
        "prior_historical_commit": "b1806a2e2c811e7ef5b15848ba262664aa34363f",
        "original_missing_archive_sha256": "a8ce9dccf74ff31521e736d52a238d57b689e3431f35157b451e82b4883327d8",
        "original_missing_final_audit_sha256": "e9cca63657c97dfbc597a8e21d20f23a203d84745c2a19bef19ac809086f98f5",
        "frozen_core_files": 11,
        "raw_data_splits": 6,
        "training_candidates": 60,
        "weight_checkpoints": checkpoint_count,
        "selected_aliases": 60,
        "exact_primary_reconstructed_artifacts": 61,
        "exact_original_numerical_raw_artifacts": 104,
        "original_report_input_availability": counts,
        "registered_metric_improvement_gates": {"passed": 0, "total": 24},
        "numerical_end_to_end": dict(e2e),
        "independent_continuous_flow": dict(dop),
        "runtime_quality_pairs": {"eligible": 8, "total": 16},
        "runtime_is_new_measurement_not_original_clock_recovery": True,
        "recovery_report_inputs": 754,
        "recovery_report_outputs": 7,
        "report_receipt_sha256": digest(report_path),
        "independent_measurements_audit_sha256": digest(
            R / "replayed_measurements_audit.json"
        ),
        "bound_artifacts": artifacts,
        "limits": [
            "No measured advantage from the analytic Call-Put shape in the registered tasks.",
            "A resolved continuous-flow state failure is retained.",
            "Old timing and execution JSON are not reconstructed from rounded report tables.",
            "Original report002 summary, original final audit and original complete archive remain unavailable.",
            "No native SNN, CfC, Mamba, Transformer, multimodal, GPU or energy superiority claim.",
        ],
    }
    write_new(FINAL, result)
    archive.gates(archive.inventory(ROOT), lambda name: (ROOT / name).read_bytes())
    print(
        json.dumps(
            {
                "status": "complete",
                "bound_artifacts": len(artifacts),
                "final_audit_sha256": digest(FINAL),
                "original_inputs": counts,
            }
        )
    )


if __name__ == "__main__":
    main()
