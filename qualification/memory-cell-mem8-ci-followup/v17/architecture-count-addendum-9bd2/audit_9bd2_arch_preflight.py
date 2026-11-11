"""Check the two existing complete 9bd2 logs and original Python receipts only."""
import hashlib
import json
from pathlib import Path

from audit_completed_records import identity, python_case_ids
from audit_arch_candidate_preflight import audit_raw

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "mem-ci-9bd2-mem-architecture"
HEAD = "9bd2f589debdba4a93baa363817c3669cb103721"
TREE = "c77785ecb368c44ea699769001a47402c9f50591"
BASE = "96038ccf0660154fac143ba6cbe4be81e00813e8"
MERGE = "6032d1f09f2b2e70c6be42336b6922fdade5f60c"

def load(path):
    return json.loads(path.read_bytes())

def canonical_ids_hash(ids):
    return hashlib.sha256(json.dumps(sorted(ids), separators=(",", ":")).encode()).hexdigest()

def receipts(artifact_id, lane, tested):
    root = ORIGINAL / "artifacts" / str(artifact_id) / "files"
    rows, all_ids = [], []
    for path in sorted(root.glob("*.json")):
        receipt = load(path)
        if not isinstance(receipt, dict) or "command" not in receipt:
            continue
        command = receipt["command"]
        if command[:3] != ["python3", "-m", "unittest"]:
            continue
        assert receipt["status"] == "passed"
        assert receipt["command_exit_code"] == receipt["exit_code"] == receipt["returncode"] == 0
        assert receipt["timed_out"] is False and receipt["output_limit_exceeded"] is False
        assert (receipt["source_sha"], receipt["tested_sha"], receipt["base_sha"], receipt["lane"]) == (HEAD, tested, BASE, lane)
        assert int(receipt["run_id"]) == 43021840388 and str(receipt["run_attempt"]) == "1"
        assert receipt["before"] == receipt["after"]
        assert receipt["before"]["commit"] == tested and receipt["before"]["tree"] == TREE and receipt["before"]["dirty"] is False
        if lane == "base-merge":
            assert receipt["before"]["parents"] == [BASE, HEAD] and receipt["recomputed_merge_tree"] == TREE
        data = (root / receipt["log_file"]).read_bytes()
        assert len(data) == receipt["log_bytes"] and hashlib.sha256(data).hexdigest() == receipt["log_sha256"]
        ids = python_case_ids(data.decode())
        assert len(ids) == receipt["observed_passed_tests"] >= receipt["minimum_tests"]
        assert receipt["observed_failed_tests"] == 0
        all_ids.extend(ids)
        rows.append({"artifact_id": artifact_id, "receipt": path.name, "receipt_identity": identity(path.read_bytes()),
                     "raw_log": receipt["log_file"], "raw_identity": identity(data), "command": command,
                     "passed": len(ids), "case_ids_canonical_sha256": canonical_ids_hash(ids),
                     "source_before_after_equal_clean": True})
    assert len(all_ids) == len(set(all_ids))
    return rows, set(all_ids)

def main():
    old = load(ORIGINAL / "ARCHITECTURE_AUDIT_V2.json")
    assert old["source_head"] == HEAD and old["source_tree"] == TREE
    assert old["source_head_lane"]["python_passed"] == 138 and old["base_merge"]["python_passed"] == 136
    assert old["source_head_lane"]["rust_passed"] == 526 and old["both_lanes_passed_execution_observations"] == 800
    rows, unions, receipt_sets = [], {}, {}
    for lane, job, artifact, tested, expected in (
        ("source-head", 130526675565, 13857194575, HEAD, 138),
        ("base-merge", 130526675057, 13855890256, MERGE, 136),
    ):
        groups, ids = receipts(artifact, lane, tested)
        assert len(ids) == expected
        row = audit_raw(ORIGINAL / "raw" / f"job-{job}-decoded.log", HEAD, TREE, tested, lane, job, ids)
        union = row.pop("all_python_execution_case_ids")
        row["all_python_case_ids_canonical_sha256"] = canonical_ids_hash(union)
        row["qualification_receipts"] = groups
        rows.append(row)
        unions[lane], receipt_sets[lane] = set(union), ids
    assert rows[0]["raw_only_case_ids"] == rows[1]["raw_only_case_ids"]
    assert receipt_sets["base-merge"].issubset(receipt_sets["source-head"])
    extra = sorted(receipt_sets["source-head"] - receipt_sets["base-merge"])
    assert extra == [
        "scripts.test_hepta_objective_contracts.ObjectiveContractAlignmentTests.test_objective_semantics_do_not_redefine_wire_fields",
        "scripts.test_hepta_objective_contracts.ObjectiveContractAlignmentTests.test_source_envelope_capacity_matches_native_lowering",
    ]
    assert len(unions["source-head"]) == 146 and len(unions["base-merge"]) == 144
    assert len(unions["source-head"] | unions["base-merge"]) == 146
    result = {"schema": "mem8.9bd2.architecture.raw-preflight-count-addendum.v1", "source_commit": HEAD, "source_tree": TREE,
              "run_id": 43021840388, "attempt": 1,
              "correction": "The historical Python138/source and136/base figures count qualification command receipts. Both original complete logs additionally contain eight CandidatePlanTests with a single literal invocation, eight actual ok outcomes, one eight-test footer and OK, and the exact candidate source binding. These are not echo/reprint duplicates.",
              "source_head_python": {"qualification_receipted": 138, "additional_raw_only": 8, "total": 146},
              "base_merge_python": {"qualification_receipted": 136, "additional_raw_only": 8, "total": 144},
              "combined_python": {"qualification_receipted_executions": 274, "additional_raw_only_executions": 16,
                                  "all_python_executions": 290, "distinct_python_case_ids": 146},
              "source_only_two_objective_contract_ids": extra,
              "existing_rust_receipt_execution_observations_unchanged": 526,
              "existing_qualification_receipted_all_language_observations_unchanged": 800,
              "all_language_execution_observations_including_16_raw_only": 816,
              "all_language_distinct_case_count_claimed": False,
              "historical_audit_identity": identity((ORIGINAL / "ARCHITECTURE_AUDIT_V2.json").read_bytes()),
              "old_raw_and_audit_bytes_modified": False, "new_tests_models_or_CI_runs": 0,
              "limits": "This scope correction does not produce missing structured command receipts or transfer results to b054/c895; Rust execution observations remain the historical separately audited count, not a newly recounted unique-case claim.",
              "jobs": rows}
    (HERE / "NINE_BD2_ARCH_CANDIDATE_COUNT_ADDENDUM.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "jobs"}, indent=2))

if __name__ == "__main__":
    main()
