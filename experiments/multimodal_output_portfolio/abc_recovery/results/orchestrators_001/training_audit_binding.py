"""Bind the sealed raw audit census to the producer's frozen result receipts."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time
import traceback


TRAINING = Path("/workspace/scratch/2b3c256bef7d/abc2-runs/training-001")
AUDIT = Path("/workspace/scratch/2b3c256bef7d/abc2-runs/training-audit-001")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    verified = []
    registration = {"schema": "hepta.abc.producer-audit-binding-registration.v1",
                    "checker_source_sha256": sha(__file__), "registered_unix_ns": time.time_ns(),
                    "training_directory": str(TRAINING), "audit_directory": str(AUDIT),
                    "scope": "Read-only checksum and complete-census binding. No output generation, rescoring, training or tuning."}
    write(AUDIT / "producer-binding-registration.json", registration)
    try:
        training, result, audit = read(TRAINING / "registration.json"), read(TRAINING / "result.json"), read(AUDIT / "result.json")
        audit_registration = read(AUDIT / "registration.json")
        require(not (TRAINING / "failure.json").exists() and not (AUDIT / "failure.json").exists(), "Producer or audit failed")
        require(read(TRAINING / "whole-process-cost.json")["exit_code"] == 0, "Producer process did not finish successfully")
        require(read(AUDIT / "whole-process-cost.json")["exit_code"] == 0, "Audit process did not finish successfully")
        expected = {(seed, arm) for seed in training["fine_tuning_census"]["training_seeds"]
                    for arm in training["fine_tuning_census"]["arms"]}
        produced = {(row["seed"], row["arm"]): row for row in result["models"]}
        checked = {(row["seed"], row["arm"]): row for row in audit["models"]}
        require(result["status"] == "completed" and result["model_count"] == len(expected) == 15,
                "Producer census is not all fifteen models")
        require(audit["status"] == "passed" and audit["all_15_arms_passed"] and audit["audited_arms"] == audit["passed_arms"] == 15
                and audit["failed_arms"] == 0 and audit["not_audited_arms"] == [], "Audit did not pass every arm")
        require(set(produced) == set(checked) == expected and len(result["models"]) == len(audit["models"]) == 15,
                "Missing or duplicate producer/audit model keys")
        totals = Counter()
        for key in sorted(expected):
            producer, record = produced[key], checked[key]
            directory = TRAINING / f"seed-{key[0]}" / key[1]
            summary_sha = sha(directory / "summary.json")
            summary = read(directory / "summary.json")
            report_path = AUDIT / "arms" / f"seed-{key[0]}-{key[1]}.json"
            report = read(report_path)
            require(producer["summary_file_sha256"] == record["input_summary_sha256"] ==
                    report["summary_file_sha256"] == summary_sha, f"Producer/audit summary SHA mismatch: {key}")
            require(producer["model_file_sha256"] == summary["checkpoint_file_sha256"] ==
                    summary["artifacts"]["model.pt"]["sha256"] == sha(directory / "model.pt"), f"Model byte identity mismatch: {key}")
            require(producer["snapshot_sha256"] == summary["final_snapshot_sha256"], f"Model snapshot identity mismatch: {key}")
            require(record["audit_report_sha256"] == sha(report_path), f"Audit report hash mismatch: {key}")
            require(report["passed"] and report["errors"] == [] and record["passed"], f"Failed per-arm audit: {key}")
            require(report["counts"]["output_rows_rescored"] == report["expected_output_rows"] == summary["terminal_output_rows"] == 51200,
                    f"Incomplete actual-output row census: {key}")
            require(report["counts"]["complete_steps_checked"] == summary["completed_steps"] == 400, f"Incomplete step census: {key}")
            require(report["counts"]["media_member_sha256_checks"] == 102400 and
                    report["counts"]["terminal_pixel_token_digest_checks"] == 51200, f"Incomplete raw media hash census: {key}")
            require(record["counts"] == report["counts"], f"Per-arm counter inconsistency: {key}")
            for name in ("training-outputs.jsonl.gz", "trajectory-ledger.jsonl.gz", "raw-media.zip"):
                require(sha(directory / name) == summary["artifacts"][name]["sha256"], f"Post-audit media/row changes: {key}/{name}")
            totals.update(report["counts"])
            verified.append({"seed": key[0], "arm": key[1], "summary_sha256": summary_sha,
                             "audit_report_sha256": record["audit_report_sha256"], "model_file_sha256": producer["model_file_sha256"]})
        require(dict(totals) == audit["total_counts"] and totals["output_rows_rescored"] == 768000,
                "Aggregate audit counters disagree")
        require(all(audit["paired_arm_batch_schedules_match_by_seed"].values()), "Cross-arm source schedules differ")
        for path, expected_sha in {**audit_registration["source_sha256"], **audit_registration["input_file_sha256"]}.items():
            require(sha(path) == expected_sha, "Registered audit dependency changed: " + path)
        receipt = {"schema": "hepta.abc.producer-audit-binding-result.v1", "status": "passed", "passed": True,
                   "verified_model_count": len(verified), "verified_models": verified, "total_counts": dict(totals),
                   "producer_result_sha256": sha(TRAINING / "result.json"), "audit_result_sha256": sha(AUDIT / "result.json"),
                   "registration_sha256": sha(AUDIT / "producer-binding-registration.json"),
                   "all_raw_training_outputs_rescored": 768000, "claimed_independent_sample_size": None,
                   "source_roles_read": [], "new_outcomes_used_for_tuning": False,
                   "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
                   "timer_scope": "Entry through all checksum/census validation; final receipt serialization measured separately below."}
        write(AUDIT / "producer-binding.json", receipt)
        write(AUDIT / "producer-binding-cost.json", {"wall_ns": time.perf_counter_ns() - wall,
              "cpu_ns": time.process_time_ns() - cpu, "includes": "checker registration, all checksum validation and final binding receipt fsync"})
        print(json.dumps({"status": "passed", "verified_models": len(verified), "rows_rescored": totals["output_rows_rescored"]}))
    except BaseException as error:
        write(AUDIT / "producer-binding-failure.json", {"status": "failed", "error": repr(error),
              "traceback": traceback.format_exc(), "verified_models_before_failure": verified,
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise


if __name__ == "__main__":
    main()
