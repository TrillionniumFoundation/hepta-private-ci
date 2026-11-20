"""Prepare a continuation checkpoint while retaining exact previous bytes."""

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PREVIOUS = "238fc48402f786db3d7f2a80b0abad6c0e5322bb"
PREVIOUS_SHA = "6d56b7f9c89fcfadb56dea8d4d21099974e364fa0d161b03a46b5c4e5dc7a06c"


def read(path):
    return json.loads((ROOT / path).read_text())


def build(config):
    original_bytes = (ROOT / "CURRENT_PROGRESS_238_original.json").read_bytes()
    assert hashlib.sha256(original_bytes).hexdigest() == PREVIOUS_SHA
    previous = json.loads(original_bytes)
    current = copy.deepcopy(previous)
    current["observed_at_utc"] = config["observed_utc"]
    current["observed_at_user_timezone"] = config["observed_local"]
    current["previous_evidence_commit"] = PREVIOUS
    if "interpretation" in config:
        current["interpretation"] = config["interpretation"]
    current["checkpoint_scope"]["previous_current_sha256"] = PREVIOUS_SHA
    current["checkpoint_scope"]["previous_current_exact_bytes"] = (
        "checkpoint-20261120/previous-current-238.json.xz"
    )
    terminal = read("e3_recovery_terminal_original.json")
    assert terminal["status"] == "FAILED_RETAIN_PARTIAL_NO_MODEL_EXECUTION"
    assert terminal["known_new_written_bytes"] == 645464064
    assert not terminal["full_lfs_sha256_verified"]
    current["E3"]["latest_independent_weight_recovery"] = {
        "status": terminal["status"],
        "pr": 6781,
        "published_evidence_head": "6cce823fcef62f3e65856d3a4ff2b428d3bd8c38",
        "published_tree": "c844e1fce1c264a6d96a916104f50c518c06097a",
        "evidence_directory": "qualification/cell-e3-independent-base-materials-20261120/recovery-execution-1",
        "unique_owner": "dpty-9c793d930ee32ba9d5e98dab865601b80aad62c8cade3c72d04e3b1fda709b67",
        "owner_terminal": True,
        "owner_exit_code": 1,
        "host": "desktop",
        "root": "/home/qian-qi/work/hepta-e3-smollm2-materials-20261120-e9e051/range-recovery-run-1",
        "execution_freeze_sha256": terminal["execution_freeze_sha256"],
        "executed_source_sha256": "eb209383a440a349f8207cbfce8416e330ebd6d456c76ab736df809c67c20bea",
        "terminal_result_sha256": "8429ccfd26c03a8266c596e7560cb728ec9bc57cf312ab3b40f7a1b549b213a2",
        "readout_sha256": "21774ca85bca8ba57ba8b74980e6a2f612b144ce5b60f5685e92fb12b5a66121",
        "fixed_workers": 4,
        "frozen_nonoverlapping_ranges": 95,
        "attempted_ranges": 22,
        "complete_ranges": 18,
        "partial_ranges": 4,
        "unknown_terminal_ranges": 0,
        "range_retries": 0,
        "complete_range_new_bytes": 603979776,
        "partial_range_new_bytes": 41484288,
        "new_received_and_written_bytes": 645464064,
        "old_readonly_prefix_bytes": 255852544,
        "unique_retained_weight_positions": 901316608,
        "required_full_weight_bytes": 3422777952,
        "missing_weight_positions": 2521461344,
        "logical_sparse_size_is_not_complete_material": True,
        "full_lfs_sha256_verified": False,
        "independent_teacher_ready": False,
        "deadline_seconds": 895,
        "owner_wall_seconds": terminal["wall_seconds"],
        "owner_self_cpu_seconds": terminal["owner_self_cpu_seconds"],
        "children_cpu_seconds": terminal["child_cpu_seconds"],
        "nested_worker_wall_not_added_to_parent": True,
        "independent_extent_readback_passed": True,
        "independent_extent_readback_seconds": 3.777683761029,
        "extent_readback_sha256": "26dcb5a827114fbcd691558d4a27746eb2a5a141e30a595655a02a58564bab34",
        "receipt_archive_sha256": "ecca78131dd1ddc82bad01707d626fed8d2d86603e35f98085dbb5cf058d5326",
        "receipt_archive_members": 90,
        "receipt_archive_member_bytes": 132152,
        "receipt_archive_bytes": 24371,
        "all_receipt_archive_members_independently_verified": True,
        "maximum_planned_HTTP_body_bytes": 3427266230,
        "original_maximum_HTTP_body_bytes": 4294967296,
        "actual_conservative_cumulative_HTTP_body_upper_bound": 998538253,
        "new_model_loads": 0,
        "new_model_forwards": 0,
        "new_model_calls": 0,
        "new_training_updates": 0,
        "new_native_children": 0,
        "third_download_owner_started": False,
        "original_T2_call_budgets_unchanged": True,
        "full_system_cost_known": False,
        "published_blob_validation_scope": "69 new paths read byte-for-byte at exact ref and checked against 512000; original blob script was not run at 6cce",
    }
    if "e6_latest" in config:
        current["E6"]["latest_original_owner_continuation"] = config["e6_latest"]
    if "e5_codec" in config:
        current["E5"]["latest_source_action_codec"] = config["e5_codec"]
    if "cold_D_review" in config:
        current["E6"]["latest_cold_D_source_review"] = config["cold_D_review"]
    current["CI"]["checkpoint_238_original_blob_validation"] = {
        "tested_head": PREVIOUS,
        "tested_tree": "74478db5dad451c13483dd575cd5d94c0a3e6864",
        "base": "e4b4eb5028578be87d5cad0829103632f2bff3a3",
        "scope": "27 incremental checkpoint changes, not full joint PR or native E6",
        "changed_files": 27,
        "maximum_bytes": 512000,
        "exit_code": 0,
        "wall_seconds": 118.31996956001967,
        "result_sha256": "58b3836819fdd1b91c81bb49452da153cd73bc0171356cf884297f9fd2f90ef9",
        "evidence_directory": "../cell-e6-metrics-integration-20261119/checkpoint-238-readback",
        "repository_identity_and_gate_bytes_unchanged": True,
    }
    if "ci_238" in config:
        current["CI"]["latest_238_workflow_observation"] = config["ci_238"]
    if "checkpoint_readbacks" in config:
        current["checkpoint_scope"]["latest_checkpoint_readbacks"] = config[
            "checkpoint_readbacks"
        ]
    assert current["joint_execution_source"] == previous["joint_execution_source"]
    assert current["joint_execution_tree"] == previous["joint_execution_tree"]
    assert current["qualification"] == previous["qualification"]
    assert len(current["qualification"]) == 10
    assert all(value is False for value in current["qualification"].values())
    assert current["historical_freeze_rewritten"] is False
    for experiment in ["E1", "E2", "E4", "Chain"]:
        assert current[experiment] == previous[experiment]
    return current


if __name__ == "__main__":
    config = read("next_checkpoint_config.json")
    value = build(config)
    output = ROOT / "next-publication/qualification/cell-joint-20261118-2e9b/CURRENT_PROGRESS.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    data = output.read_bytes()
    assert len(data) <= 512000
    print(json.dumps({"path": str(output), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}))
