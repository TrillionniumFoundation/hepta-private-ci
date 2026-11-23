"""Bind current students' first A failures to existing verified repair targets."""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

SCHEMA = "hepta.current-student-correction.v1"
SOURCE = "e147c1d851b0a5b5c03dbeb0285d443bd7057973"
READER_SHA = "3b9daa355478483e5e4446ce6d3de84e649cfb9d0aab0a163ae5c80ad27b9f8d"
ORIGINAL_PROTOCOL_SHA = "e5907ac5c963919d1a947df5274bb6e4a84565ab52f0478eabca91334b3739b5"
BASE = Path("qualification/cell-upstream-raw-function-learning-20261119")
MODES = ("document_evidence", "native_feedback")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def load_reader(root):
    path = Path(root) / "scripts/cell_experiments/e2_current_state_readback.py"
    require(sha(path) == READER_SHA, "pinned current-state reader changed")
    spec = importlib.util.spec_from_file_location("current_state_readback", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_parent(manifest, loaded, raw_sha):
    require(manifest["schema"] == "hepta.upstream-raw-function-sft-model.v1",
            "current raw-function student required")
    require(raw_sha == loaded["manifest_sha256"], "parent manifest bytes changed")
    require(digest(manifest) == loaded["model_digest"], "parent model identity changed")
    require(manifest["parameter_after"] == loaded["actual_parameter_digest_verified_by_loader"],
            "current student parameters differ")
    require(manifest["parameter_before"] != manifest["parameter_after"],
            "common pretraining parent cannot replace the current student")


def assemble(root):
    root = Path(root)
    reader = load_reader(root)
    checked = reader.readback(root)
    pinned, members, _ = reader.read_inputs(root)
    protocol_path = root / BASE / "prepared/PROTOCOL.json"
    require(sha(protocol_path) == ORIGINAL_PROTOCOL_SHA, "original engine protocol changed")
    original_protocol = json.loads(protocol_path.read_bytes())
    targets = {row["project_id"]: row for row in pinned["prepared/DATASET.json"]}
    parents, records = {}, {mode: [] for mode in MODES}
    for mode in MODES:
        loaded = json.loads(members[f"evaluation-A/{mode}/MODEL_LOADED.json"])
        path = root / BASE / "training" / mode / "manifest.json"
        parent = json.loads(path.read_bytes())
        check_parent(parent, loaded, sha(path))
        require(parent["objective"] == mode, "student evidence identity differs")
        parents[mode] = {"manifest": parent, "manifest_sha256": sha(path),
                         "model_digest": loaded["model_digest"],
                         "parameter_digest": parent["parameter_after"]}
    seen = set()
    for state in checked["failed_native_state_reconstructions"]:
        mode, project = state["mode"], state["project"]
        key = (mode, project)
        if key in seen:
            continue
        seen.add(key)
        folder = state["record"]
        request = json.loads(members[folder + "/REQUEST.json"])
        answer = json.loads(members[folder + "/OUTPUT.json"])
        feedback = json.loads(members[folder + "/FEEDBACK.json"])
        verification = json.loads(members[folder + "/VERIFICATION.json"])
        target = targets[project]
        require(target["authorization"].get("training_allowed") is True,
                "A source is not authorized for training")
        require(answer["loaded_model_manifest_digest"] == parents[mode]["model_digest"],
                "another policy's failure cannot train this student")
        require(verification["actual_native_child"] and not verification["success"],
                "only actually executed own failures may enter correction training")
        require(state["reconstructed_after_sha256"] == target["reference_exact_after_sha256"],
                "correction does not reconstruct the already verified AFTER state")
        prefix = copy.deepcopy(request["task"]["messages"])
        prefix.extend([{"role": "assistant", "content": answer["answer"]},
                       {"role": "tool", "content": feedback["content"]}])
        record = {
            "record_id": folder + ":own-correction",
            "task_id": target["task_id"], "project_id": project, "split": "train",
            "authorization": copy.deepcopy(target["authorization"]),
            "observed_actor_model_digest": parents[mode]["model_digest"],
            "initial_messages": prefix, "final_answer": target["final_answer"],
            "current_failed_state": copy.deepcopy(state),
            "original_task": copy.deepcopy(request["task"]),
            "observed_actions_are_targets": False,
            "verified_positive_intermediate_actions": 0,
            "target_kind": target["target_kind"],
        }
        record["record_digest"] = digest(record)
        records[mode].append(record)
    require(all(len(rows) == 2 for rows in records.values()),
            "fixed first-native-failure A coverage differs")
    return {
        "schema": SCHEMA, "evidence_head": SOURCE, "reader_sha256": READER_SHA,
        "selection": "first actual native failure per current student and A project",
        "parents": parents, "records": records,
        "readback_digest": digest(checked),
        "training_engine_identity": original_protocol["training_engine_identity"],
        "original_protocol_sha256": ORIGINAL_PROTOCOL_SHA,
        "original_own_policy_counts": checked["original_own_policy_counts"],
        "original_budget_spent": checked["original_budget_spent"],
        "retained_admission_refusals": checked["first_admission_refusals"],
        "all_failed_native_state_bindings": checked["failed_native_state_reconstructions"],
        "new_native_execution": 0, "new_model_calls": 0, "new_optimizer_updates": 0,
        "future_task_or_answer_files_read": False,
        "independent_projects_per_parent": 2,
        "all_actions_equals_final_only": True,
        "scientific_confirmation_qualified": False, "native_adoption": False,
    }


def verify_bundle(bundle):
    require(bundle["schema"] == SCHEMA and bundle["evidence_head"] == SOURCE,
            "unexpected correction evidence identity")
    for mode in MODES:
        parent = bundle["parents"][mode]
        require(digest(parent["manifest"]) == parent["model_digest"], "parent changed")
        for record in bundle["records"][mode]:
            row = copy.deepcopy(record)
            expected = row.pop("record_digest")
            require(digest(row) == expected, "record content changed")
            require(row["split"] == "train" and row["authorization"]["training_allowed"],
                    "record must be authorized A training evidence")
            require(row["observed_actor_model_digest"] == parent["model_digest"],
                    "cross-student training evidence rejected")
            require(not row["observed_actions_are_targets"], "failed action label rejected")


def freeze(root, output):
    bundle = assemble(root)
    verify_bundle(bundle)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    write_new(destination / "CORRECTIONS.json", bundle)
    settings = copy.deepcopy(bundle["parents"]["native_feedback"]["manifest"]["training_settings"])
    settings["steps"] = 8
    protocol = {
        "schema": "hepta.current-student-correction-protocol.v1",
        "candidate_name": "current-student-own-A-correction-20261121",
        "corrections_digest": digest(bundle),
        "source_files": {p.name: sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
        "training_settings": settings,
        "training_variants": ["final_only"],
        "correction_evidence_layout": "native_chat_v2",
        "two_parents_are_separate_continuation_experiments": True,
        "optimizer_updates_per_parent": 8, "optimizer_updates_global_cap": 16,
        "independent_parent_initializations": {m: bundle["parents"][m]["parameter_digest"] for m in MODES},
        "no_update_controls": ["frozen", "retrieval"],
        "all_actions_status": "identical final target only; no positive intermediate action evidence",
        "new_generation_call_cap": 0, "new_native_execution_cap": 0,
        "automatic_retry": False, "parent_adapters_must_remain_unchanged": True,
        "old_experiment_budget_extension": False,
        "fresh_confirmation": "requires a separately frozen unexposed panel and new bounded evaluation protocol",
        "old_four_future_tasks_eligible_for_blind_confirmation": False,
        "scientific_confirmation_qualified": False, "native_adoption": False,
    }
    protocol["candidate_digest"] = digest(protocol)
    write_new(destination / "PROTOCOL.json", protocol)
    return protocol


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.source_root, args.output), indent=2))
