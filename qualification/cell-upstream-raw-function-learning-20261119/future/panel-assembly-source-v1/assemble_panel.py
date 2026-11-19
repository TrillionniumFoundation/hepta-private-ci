"""Freeze four qualified original tasks before any new A or future generation."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import future_native as native

WORK = Path("/home/qian-qi/work/hepta-upstream-raw-function-learning-20261119-2e9b")
WEIGHTS_SHA = "237ae92fc94d6ae411671c671190314049ded5cdc0d5dae254d57c9d8bb67be6"
OLD_INVENTORY_SHA = "aa522307a3d06aba4ac355846cba05417c0a9dc06a88b834d618b414247c1d9a"


def checked(path, expected):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("frozen original file changed: " + str(path))
    return json.loads(raw)


def build(config_path, output):
    config = json.loads(Path(config_path).read_bytes())
    if (
        native.sha(Path(native.__file__).read_bytes())
        != "a36a3880753aea81019cdecb35554af859839c7b7d7941f7a5e0e07c08bbafaa"
    ):
        raise ValueError("frozen native runtime source changed")
    weights = checked(WORK / "WEIGHTS_FROZEN.json", config["weights_frozen_sha256"])
    old_inventory = checked(
        WORK / "future-preparation-old-inventory-1/DEDUP_INVENTORY.json",
        OLD_INVENTORY_SHA,
    )
    old_projects = {
        row.get("canonical_repository", row.get("repository"))
        for row in old_inventory["repositories"]
    }
    if config["weights_frozen_sha256"] != WEIGHTS_SHA:
        raise ValueError("this panel belongs to different actual frozen weights")
    if weights["status"] != "MATCHED_AND_WEIGHTS_FROZEN":
        raise ValueError("actual weights are not frozen")
    if (WORK / "evaluation-A").exists() or (WORK / "evaluation-future").exists():
        raise ValueError("new evaluation output already exists before panel freeze")
    selection = checked(config["selection_path"], config["selection_sha256"])
    if (
        len(config["selected"]) != selection["panel_size"]
        or selection["panel_size"] != 4
    ):
        raise ValueError("exactly four tasks are required")
    repositories = selection["candidate_repositories_in_order"]
    tasks, proofs, positions, fingerprints = [], [], [], set()
    for row in config["selected"]:
        prepared = Path(row["preparation_root"])
        qualification = prepared.parent
        task = checked(prepared / "TASK.json", row["task_sha256"])
        context = checked(prepared / "RESULT.json", row["context_result_sha256"])
        if (
            context["preparation_source_sha256"]
            != "cf3e7d0e207b5553618d6eee436b2550d6205c76151b655296c4e193d1a7fbbc"
        ):
            raise ValueError("the common complete-context preparation source changed")
        pair = checked(qualification / "RESULT.json", row["native_pair_sha256"])
        if (
            context["status"] != "CODEC_CONTEXT_DEDUP_PASSED_PENDING_LICENSE"
            or pair["status"] != "ORIGINAL_NATIVE_PAIR_PASSED"
        ):
            raise ValueError(
                "real original native or complete-context qualification failed"
            )
        if (
            task["native_pair_result_sha256"] != row["native_pair_sha256"]
            or context["task_sha256"] != row["task_sha256"]
        ):
            raise ValueError("original task qualification bindings differ")
        if (
            task["weights_frozen_sha256"] != config["weights_frozen_sha256"]
            or task["training_allowed"]
        ):
            raise ValueError("future task weights or authorization differ")
        if (
            not task["newly_selected_after_actual_weight_freeze"]
            or not task["no_model_output_used_for_selection"]
        ):
            raise ValueError("future selection contract differs")
        project = task["project_id"]
        if project in old_projects or task["old_inventory_sha256"] != OLD_INVENTORY_SHA:
            raise ValueError("original old-project exclusion inventory differs")
        positions.append(repositories.index(project))
        review = checked(row["license_review_path"], row["license_review_sha256"])
        reviewed = [
            entry
            for entry in review["entries"]
            if entry["canonical_repository"] == project
        ]
        if (
            len(reviewed) != 1
            or not reviewed[0][
                "license_condition_for_current_material_retention_satisfied"
            ]
        ):
            raise ValueError("original license review is missing")
        if reviewed[0]["task_sha256"] != row["task_sha256"]:
            raise ValueError("license review belongs to another task")
        for notice in reviewed[0]["original_notices"]:
            raw = Path(notice["path"]).read_bytes()
            if len(raw) != notice["bytes"] or native.sha(raw) != notice["sha256"]:
                raise ValueError("retained original license or notice changed")
        spec = native.bound(task["task_spec_path"], task["task_spec_sha256"])
        if (
            spec["project_id"] != project
            or spec["before_sha256"] != task["original_source_sha256"]
        ):
            raise ValueError("original native specification differs")
        identity = {
            ("file", task["original_source_sha256"]),
            ("file", task["original_after_sha256"]),
            *(
                ("function_AST", value)
                for value in task["before_after_function_AST_sha256"]
            ),
            *(
                ("test_AST", value["normalized_ast_sha256"])
                for value in spec["test_ast"]
            ),
        }
        if identity & fingerprints:
            raise ValueError("new tasks overlap in bound source/function/test identity")
        fingerprints.update(identity)
        before, after = pair["before"], pair["after"]
        if not (
            before["actual_wait_returncode"] == 1
            and before["failures"] > 0
            and before["errors"] == before["skipped"] == 0
            and not before["timed_out"]
            and after["success"]
            and after["actual_wait_returncode"] == 0
            and after["failures"] == after["errors"] == after["skipped"] == 0
            and pair["same_original_case_set"]
            and pair["expected_cases"] == task["expected_cases"]
        ):
            raise ValueError("strict original BEFORE/AFTER case gate differs")
        preflight = checked(
            prepared / "TOKENIZER_PREFLIGHT.json", row["tokenizer_preflight_sha256"]
        )
        if (
            preflight["truncations"] != 0
            or preflight["planned_second_total"] > 8192
            or preflight["reference_output_tokens"] > 2048
        ):
            raise ValueError("complete common context budget differs")
        tasks.append(task)
        proofs.append(
            {
                **row,
                "project_id": project,
                "original_parent": pair["parent"],
                "original_commit": pair["commit"],
                "commit_index": pair["commit_index"],
                "source_index": pair["source_index"],
                "actual_original_case_count": len(task["expected_cases"]),
                "before_failed_cases": before["failures"],
                "after_failed_cases": after["failures"],
                "first_input_tokens": preflight["first"]["tokens"],
                "planned_second_input_tokens": preflight["planned_second_total"],
                "reference_output_tokens": preflight["reference_output_tokens"],
                "task_spec_sha256": task["task_spec_sha256"],
                "tokenizer_preflight_sha256": native.sha(
                    (prepared / "TOKENIZER_PREFLIGHT.json").read_bytes()
                ),
            }
        )
    if positions != sorted(set(positions)) or len(tasks) != 4:
        raise ValueError(
            "declared project order or maximum one task per project differs"
        )
    audit = checked(config["selection_audit_path"], config["selection_audit_sha256"])
    if (
        audit["selected_projects_in_declared_order"]
        != [task["project_id"] for task in tasks]
        or audit["new_model_calls"] != 0
    ):
        raise ValueError("retained ordered selection audit differs")
    protocol = {
        "schema": "hepta.raw-function-future-evaluation.v1",
        "qualification_status": "FOUR_ORIGINAL_PAIRS_CONTEXTS_LICENSES_AND_DEDUP_FROZEN",
        "prepared_at_ns": str(time.time_ns()),
        "weights_frozen_sha256": config["weights_frozen_sha256"],
        "training_source_commit": "2b85ea867e2749d4dc3bbb75ac16c9b5f9344f82",
        "selection_appendix_sha256": config["selection_sha256"],
        "old_inventory_sha256": OLD_INVENTORY_SHA,
        "selection_audit_sha256": config["selection_audit_sha256"],
        "selected_projects_in_declared_order": [task["project_id"] for task in tasks],
        "primary_arm": "native_feedback",
        "control_arm": "document_evidence",
        "parent_arm": "P",
        "global_new_generation_cap": 56,
        "A_new_generation_cap": 24,
        "future_new_generation_cap": 32,
        "future_schedule": {
            "P": {"own_prefix": 8, "common_P_prefix": 0},
            "document_evidence": {"own_prefix": 8, "common_P_prefix": 4},
            "native_feedback": {"own_prefix": 8, "common_P_prefix": 4},
        },
        "common_information_and_verifier_opportunities": True,
        "actual_current_policy_second_turn": "Exact first answer followed by the actual bounded verifier feedback.",
        "common_P_prefix": "Exact frozen actual parent first answer and feedback, with the identical parent's second-call request; no reference answer substituted.",
        "max_input_tokens": 8192,
        "max_output_tokens": 2048,
        "native_context_tokens": 32768,
        "truncation_allowed": False,
        "every_actual_complete_context_checked_before_generation": True,
        "same_greedy_generation_policy_as_original_A": True,
        "cuda_memory_fraction": 0.70,
        "inference_attention": "eager",
        "new_training_updates": 0,
        "native_runtime_source_sha256": native.sha(Path(native.__file__).read_bytes()),
        "cost_source_v5_changes": "Only actual inner CPU observation; original native decisions and older pair results remain unchanged.",
        "CPU_scopes_not_additive": True,
        "full_system_cost_known": False,
        "decision_rule": {
            "primary_each_panel": "native final success set strictly larger than P, includes every P final success, and native common-prefix successes preserve every successful P second call.",
            "primary_requires_both_A_and_future": True,
            "native_unique_mechanism_separately_each_panel": "native common-prefix success set strictly contains document common-prefix success set.",
            "selected_any_attempt_never_replaces_final": True,
            "prior_NoUpdate_results_unchanged": True,
        },
        "origin_kind": "curated_development",
        "split": "confirmation",
        "selected_after_actual_weight_freeze_before_any_new_A_or_future_generation": True,
        "authenticated_users": 0,
        "authenticated_independent_controller": False,
        "pretraining_contamination_eliminated": False,
        "native_adoption": False,
        "complete_E1_retrieval_control_or_E5_growth_curves_established": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    native.write(output / "TASKS.json", tasks)
    native.write(output / "QUALIFICATION_INDEX.json", proofs)
    native.write(
        output / "SELECTION_AUDIT.json",
        Path(config["selection_audit_path"]).read_bytes(),
    )
    native.write(output / "PROTOCOL.json", protocol)
    native.write(
        output / "PREPARATION.json",
        {
            "config_path": str(config_path),
            "config_sha256": native.sha(Path(config_path).read_bytes()),
            "source_sha256": native.sha(Path(__file__).read_bytes()),
            "files": {
                name: native.sha((output / name).read_bytes())
                for name in (
                    "TASKS.json",
                    "QUALIFICATION_INDEX.json",
                    "SELECTION_AUDIT.json",
                    "PROTOCOL.json",
                )
            },
            "new_model_calls": 0,
            "new_native_children": 0,
            "new_training_updates": 0,
            "weights_loaded": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "FOUR_TASKS_PREPARED_PENDING_GIT_PUBLICATION",
                "directory": str(output),
                "tasks_sha256": native.sha((output / "TASKS.json").read_bytes()),
                "protocol_sha256": native.sha((output / "PROTOCOL.json").read_bytes()),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    build(Path(args.config), Path(args.output))
