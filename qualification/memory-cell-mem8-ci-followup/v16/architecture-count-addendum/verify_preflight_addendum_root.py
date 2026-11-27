"""Independently verify the additive count correction against complete original logs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
SOURCE = WORK / "mem-ci-c895-original"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def main():
    report_path = SOURCE / "ARCH_CANDIDATE_RAW_ONLY_COUNT_ADDENDUM.json"
    before = report_path.read_bytes()
    assert identity(before) == {
        "bytes": 57858,
        "sha256": "1ff6c01b7033188995ff9448ef2bc72ff07f81f12563bcf98b149bc35ad34911",
        "git_blob": "ea2c005cc90ce4920c02c46b1700b3d18ad2a459",
    }
    report = json.loads(before)
    ids = report["all_144_case_ids"]
    assert len(ids) == len(set(ids)) == 144
    digest = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
    for job in report["jobs"]:
        raw = Path(job["raw_file"]).read_bytes()
        assert identity(raw) == job["full_raw"]
        lines = raw.splitlines(keepends=True)
        for record in [job["literal_invocation"], *job["case_results"], job["source_binding"]]:
            line = lines[record["line"] - 1]
            assert line.decode().rstrip("\r\n") == record["text"]
            assert hashlib.sha256(line).hexdigest() == record["sha256_including_line_ending"]
        block = job["original_result_block"]
        block_raw = b"".join(lines[block["first_line"] - 1:block["last_line"]])
        assert all(identity(block_raw)[key] == block[key] for key in identity(block_raw))
        assert block_raw.decode() == block["text"]
        assert job["all_python_case_ids_canonical_json_sha256"] == digest
        assert len(job["case_results"]) == job["raw_only_passed"] == 8
        assert job["qualification_receipt_unique_ids"] == 136
        assert job["all_python_executions_in_this_lane"] == 144
        assert job["raw_only_ids_disjoint_from_qualification_receipt_ids"] is True
        assert job["structured_command_receipt_for_this_preflight"] is False
    assert len(report["jobs"]) == 4
    completed = subprocess.run([sys.executable, "-B", str(SOURCE / "audit_arch_candidate_preflight.py")],
                               cwd=WORK, capture_output=True, check=True)
    assert report_path.read_bytes() == before
    (HERE / "ARCH_PREFLIGHT_ROOT_REPLAY.stdout").write_bytes(completed.stdout)
    assert not completed.stderr
    result = {
        "schema": "mem8.architecture.preflight.root-addendum-audit.v1",
        "status": "PASS_COMPLETE_ORIGINAL_LINES_AND_UNCHANGED_OFFLINE_REPLAY",
        "addendum": identity(before),
        "original_jobs": [{"job": row["job_id"], "source": row["source_commit"],
                           "lane": row["lane"], "full_raw": row["full_raw"]} for row in report["jobs"]],
        "per_source_counts": report["per_source_counts"],
        "all_literal_invocations_results_summaries_and_source_bindings_verified": True,
        "original_receipt_scope_of_136_unchanged": True,
        "additional_8_case_ids_disjoint_from_136_receipt_ids": True,
        "full_original_verifier_replayed_without_change": True,
        "full_replayed_addendum_bytes_equal": True,
        "original_raw_and_historical_audits_modified": False,
        "new_native_tests_CI_runs_or_model_requests": 0,
        "limit": "The extra eight outcomes are raw-only preflight cases; no missing structured per-command receipt or native qualification is inferred.",
    }
    (HERE / "ROOT_ARCH_PREFLIGHT_ADDENDUM_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
