"""Recompute arithmetic from read-only original C2 observations.

This reads no model checkpoint, executes no training, and does not reconstruct
the missing original controller lifetime. Producer claims remain labeled.
"""

import hashlib
import json
import zipfile
import gzip
from collections import Counter
from pathlib import Path


HERE = Path(__file__).parent
ROSTER = tuple(
    f"hcsn-s{seed}-lr{rate}"
    for seed in (101, 211, 307)
    for rate in ("0.001", "0.003")
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit():
    files_path = HERE / "originals" / "FILES.json.gz"
    journal_path = HERE / "originals" / "JOURNAL.json.gz"
    status_path = HERE / "originals" / "NATIVE_STATUS.json"
    inventory = json.loads(gzip.decompress(files_path.read_bytes()))
    journals = json.loads(gzip.decompress(journal_path.read_bytes()))
    native_status = json.loads(status_path.read_text())
    archive_path = HERE / "original-c2-journals-and-results.zip"
    if sha(archive_path) != "7f2001bcc178e78c5f8de120007110e93534ba5a19e490fff307065e5466d2c3":
        raise ValueError("original C2 archive digest differs")
    with zipfile.ZipFile(archive_path) as archive:
        raw_files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(raw_files["MANIFEST.json"])["files"]
    if set(raw_files) != set(manifest) | {"MANIFEST.json"}:
        raise ValueError("original C2 archive member coverage differs")
    for name, expected in manifest.items():
        raw = raw_files[name]
        if (len(raw) != expected["bytes"]
                or hashlib.sha256(raw).hexdigest() != expected["sha256"]):
            raise ValueError("original C2 member identity differs: " + name)
    files = {item["fit"]: item for item in inventory["fits"]}
    events = {item["fit"]: item for item in journals}
    if set(files) != set(ROSTER) or set(events) != set(ROSTER):
        raise ValueError("original six-fit denominator differs")
    rows = []
    for name in ROSTER:
        observed = files[name]
        journal = events[name]
        raw_journal = raw_files[f"fits/{name}/events.jsonl"]
        if hashlib.sha256(raw_journal).hexdigest() != observed["event_summary"]["sha256"]:
            raise ValueError("original journal differs from live observation")
        parsed, bad_lines = [], []
        for number, line in enumerate(raw_journal.splitlines(), 1):
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                bad_lines.append(number)
        kinds = dict(Counter(event["kind"] for event in parsed))
        if kinds != journal["event_kinds"] or len(bad_lines) != journal["bad_tail_count"]:
            raise ValueError("original event recount differs from live observation")
        row = {
            "fit": name,
            "valid_journal_kind_counts": kinds,
            "invalid_tail_lines": len(bad_lines),
            "invalid_journal_line_numbers": bad_lines,
            "events_sha256": observed["event_summary"]["sha256"],
            "terminal_result_present": observed.get("attempt_result") is not None,
            "zero_byte_files": [
                item["name"] for item in observed["files"] if item["bytes"] == 0
            ],
            "independent_model_or_training_replay": False,
        }
        reported = journal.get("reported")
        attempt = observed.get("attempt_result")
        if reported is not None:
            if attempt is None:
                raise ValueError("fit result lacks outer result observation")
            if attempt["result"]["sha256"] != observed["result_sha256"]:
                raise ValueError("observed fit digest differs from outer result")
            raw_result = raw_files[f"fits/{name}/result.json"]
            if hashlib.sha256(raw_result).hexdigest() != observed["result_sha256"]:
                raise ValueError("original result differs from live observation")
            original_result = json.loads(raw_result)
            if original_result["selected_development"] != reported["selected_development"]:
                raise ValueError("original development metrics differ")
            matrix = original_result["selected_development"]["confusion_matrix"]
            classes = len(matrix)
            if classes != 11 or any(len(row) != classes for row in matrix):
                raise ValueError("development confusion geometry differs")
            if any(type(n) is not int or n < 0 for row in matrix for n in row):
                raise ValueError("confusion entries are not nonnegative counts")
            count = sum(map(sum, matrix))
            accuracy = sum(matrix[i][i] for i in range(classes)) / count
            f1 = 0.0
            for i in range(classes):
                denominator = sum(matrix[i]) + sum(row[i] for row in matrix)
                f1 += 2.0 * matrix[i][i] / denominator if denominator else 0.0
            f1 /= classes
            original = reported["selected_development"]
            residual = max(abs(accuracy - original["accuracy"]),
                           abs(f1 - original["macro_f1_11_classes"]))
            row.update({
                "result_sha256": observed["result_sha256"],
                "development_events": count,
                "recomputed_accuracy": accuracy,
                "recomputed_macro_f1_11_classes": f1,
                "reported_accuracy": original["accuracy"],
                "reported_macro_f1_11_classes": original["macro_f1_11_classes"],
                "metric_arithmetic_max_abs_difference": residual,
                "producer_training_adequacy_established": reported[
                    "training_adequacy_established"
                ],
                "producer_cumulative_epochs_completed": reported[
                    "cumulative_epochs_completed"
                ],
                "producer_best_epoch": reported["best_epoch"],
                "producer_child_cpu_seconds": attempt["child_cpu_seconds"],
                "producer_whole_process_wall_seconds": attempt[
                    "whole_process_wall_seconds"
                ],
                "producer_child_peak_rss_bytes": attempt["child_peak_rss_bytes"],
                "producer_whole_training_domain": reported["whole_training_domain"],
                "producer_scientific_admission": reported["scientific_admission"],
            })
        rows.append(row)
    return {
        "schema": "hcsn-original-c2-readonly-arithmetic-v1",
        "observation_date_utc": "2026-11-19",
        "original_host": "desktop",
        "original_native_job_id": "1a1c74f3308-be2a-75",
        "read_only_inventory_job_id": "1a1f228e421-ffbe-a44",
        "read_only_journal_job_id": "1a1f22e79ea-ffbe-a5e",
        "original_root": (
            "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/"
            "c2-native-execution-20261110-c385-v1"
        ),
        "source_files_sha256": {
            "audit.py": sha(Path(__file__)),
            "originals/FILES.json.gz": sha(files_path),
            "originals/JOURNAL.json.gz": sha(journal_path),
            "originals/NATIVE_STATUS.json": sha(status_path),
            "original-c2-journals-and-results.zip": sha(archive_path),
        },
        "original_archive_members_verified": len(manifest),
        "original_journals_recounted": len(ROSTER),
        "controller_result_present": inventory["controller_result_exists"],
        "native_status": native_status,
        "roster_count": len(ROSTER),
        "observed_producer_terminal_results": sum(
            row["terminal_result_present"] for row in rows
        ),
        "observed_c2_optimizer_completed_lower_bound": sum(
            row["valid_journal_kind_counts"].get("optimizer_completed", 0)
            for row in rows
        ),
        "observed_c2_optimizer_started_lower_bound": sum(
            row["valid_journal_kind_counts"].get("optimizer_started", 0)
            for row in rows
        ),
        "independent_full_training_replay_completed": 0,
        "independent_full_training_replay_denominator": 6,
        "complete_controller_lifetime_accounting": False,
        "training_started_by_this_audit": False,
        "original_artifacts_modified": False,
        "metric_scope": "producer selected development confusion matrices only",
        "inventory_event_summary_caveat": (
            "FILES.json preserves an initial parser that looked for event/type; "
            "its UNKNOWN/update_count fields are not used. JOURNAL.json correctly "
            "counts the original kind field."
        ),
        "status": "PARTIAL_ORIGINAL_EVIDENCE_CONTROLLER_TERMINAL_UNKNOWN",
        "fits": rows,
    }


if __name__ == "__main__":
    output = HERE / "RECONCILIATION.json"
    output.write_text(json.dumps(audit(), indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(output)
