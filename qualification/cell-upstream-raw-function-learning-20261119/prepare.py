"""Freeze four real P prefixes and common raw-function targets without model calls."""

import argparse
import copy
import hashlib
import inspect
import time

import raw_context as ctx
import raw_sft as fit


def build(source_commit):
    codec, parent, tasks, inference = ctx.originals()
    ctx.require(
        tuple(task["project_id"] for task in tasks) == ctx.PROJECTS,
        "fixed four A sources",
    )
    ctx.require(ctx.digest(parent) == fit.PARENT, "fixed parent required")
    reference_rows = ctx.read(ctx.COLLECTION / "cpu-attempt-1/prepared/REFERENCES.json")
    references = {row["project_id"]: row for row in reference_rows}
    files = {str(ctx.COLLECTION / name): digest for name, digest in ctx.FIXED.items()}
    files[str(ctx.PARENT_PATH)] = ctx.PARENT_SHA
    deployment = ctx.read(ctx.COLLECTION / "DEPLOYMENT.json")
    files.update(deployment["external_source_files"])
    files.update(
        {
            str(ctx.COLLECTION / "execution-source-2" / name): value
            for name, value in deployment["candidate_files"].items()
        }
    )
    parent_reuse = {}
    records = []

    def retained(path):
        files[str(path)] = ctx.sha(path)
        return ctx.read(path)

    for index, task in enumerate(tasks):
        folder = ctx.COLLECTION / "results/P" / str(index)
        for attempt in (0, 1):
            for kind in ("REQUEST", "OUTPUT", "VERIFICATION", "FEEDBACK"):
                path = folder / (kind + "-" + str(attempt) + ".json")
                retained(path)
                parent_reuse[str(path)] = files[str(path)]
        output = retained(folder / "OUTPUT-0.json")
        receipt = retained(folder / "VERIFICATION-0.json")
        feedback = retained(folder / "FEEDBACK-0.json")
        request = retained(folder / "REQUEST-0.json")
        ctx.require(
            request == {"record_id": task["record_id"], "task": task["task"]},
            "actual first P task changed",
        )
        ctx.require(
            output["loaded_model_manifest_digest"] == fit.PARENT,
            "actual current P identity differs",
        )
        ctx.require(
            receipt["raw_answer_sha256"]
            == hashlib.sha256(output["answer"].encode()).hexdigest()
            and feedback["verification_digest"] == ctx.digest(receipt)
            and feedback["content"] == codec.feedback(receipt),
            "exact own answer and real feedback required",
        )
        ctx.require(
            receipt["actual_native_child"] and receipt["stage"] == "native_pytest",
            "first prefixes require the actually observed native execution",
        )
        reference = references[task["project_id"]]
        record = {
            "record_id": task["record_id"] + ":P:first:raw-function",
            "task_id": task["task_id"],
            "project_id": task["project_id"],
            "source_path": task["source_path"],
            "source_index": index,
            "original_source_sha256": task["original_source_sha256"],
            "original_tests_sha256": task["original_tests_sha256"],
            "split": "train",
            "authorization": copy.deepcopy(task["authorization"]),
            "task": copy.deepcopy(task["task"]),
            "observed_actor": "P",
            "actual_observed_attempt": 0,
            "observed_answer": output["answer"],
            "observed_feedback": feedback["content"],
            "observed_success": receipt["success"],
            "observed_output_sha256": ctx.sha(folder / "OUTPUT-0.json"),
            "observed_verification_sha256": ctx.sha(folder / "VERIFICATION-0.json"),
            "observed_feedback_sha256": ctx.sha(folder / "FEEDBACK-0.json"),
            "final_answer": reference["payload"],
            "reference_payload_sha256": reference["payload_sha256"],
            "reference_exact_after_sha256": reference["exact_after_sha256"],
            "reference_cpu_qualification_sha256": ctx.FIXED[
                "cpu-attempt-1/cpu-controls-1/RESULT.json"
            ],
            "target_kind": "exact_original_upstream_maintainer_repair_in_common_function_codec",
            "observed_action_supervised": False,
            "teacher_2_used_as_target": False,
            "second_duplicate_P_response_not_added_as_another_training_record": True,
        }
        record["information_digest"] = fit.information(record)
        records.append(record)
    receipts = fit.verified_references(records)
    from transformers import AutoTokenizer
    import torch

    ctx.require(
        not torch.cuda.is_initialized(), "CPU preparation must not initialize a GPU"
    )
    tokenizer = AutoTokenizer.from_pretrained(
        str(ctx.ARTIFACT / parent["runtime"]["base_directory"]),
        local_files_only=True,
        trust_remote_code=False,
    )
    ctx.require(
        fit.legacy.chat_protocol.template_digest(tokenizer.chat_template)
        == parent["runtime"]["chat_template_sha256"],
        "fixed chat template required",
    )
    groups = {
        mode: fit.encode_groups(
            tokenizer, records, fit.SETTINGS["sequence_tokens"], mode
        )
        for mode in fit.MODES
    }
    summaries = {}
    for mode, values in groups.items():
        summaries[mode] = []
        for index, parts in enumerate(values):
            target_ids = [
                value for part in parts for value in part["labels"] if value != -100
            ]
            positions = [
                position
                for part in parts
                for position, value in enumerate(part["labels"])
                if value != -100
            ]
            ctx.require(
                len(positions) == len(set(positions))
                and positions == sorted(positions),
                "every causal target position must be supervised exactly once",
            )
            ctx.require(
                all(part["input_ids"] == parts[0]["input_ids"] for part in parts),
                "head chunks must preserve the same complete input",
            )
            ctx.require(
                all(
                    position >= parts[0]["prefix_tokens"] and position > 0
                    for position in positions
                ),
                "prior observed actions must remain entirely masked",
            )
            summaries[mode].append(
                {
                    "record_id": records[index]["record_id"],
                    "information_digest": records[index]["information_digest"],
                    "encoded_group_digest": ctx.digest(parts),
                    "target_ids_digest": ctx.digest(target_ids),
                    "model_forwards_per_step": len(parts),
                    "model_backwards_per_step": len(parts),
                    "complete_input_tokens_per_forward": len(parts[0]["input_ids"]),
                    "prefix_tokens": parts[0]["prefix_tokens"],
                    "supervised_positions_per_step": len(target_ids),
                    "padded_positions_per_step": fit.SETTINGS["sequence_tokens"]
                    * len(parts),
                }
            )
    equal = (
        "record_id",
        "information_digest",
        "target_ids_digest",
        "model_forwards_per_step",
        "model_backwards_per_step",
        "supervised_positions_per_step",
        "padded_positions_per_step",
    )
    for left, right in zip(summaries[fit.MODES[0]], summaries[fit.MODES[1]]):
        ctx.require(
            {key: left[key] for key in equal} == {key: right[key] for key in equal},
            "common information/targets/padded computation differ",
        )
    negatives = []
    for mode in fit.MODES:
        changed = copy.deepcopy(records[0])
        changed["observed_answer"] += "tampered"
        for kind, values, limit in (
            (
                "modified_observation_with_original_digest",
                [changed],
                fit.SETTINGS["sequence_tokens"],
            ),
            ("input_limit_cannot_truncate_complete_transcript", [records[0]], 1),
        ):
            try:
                fit.encode_groups(tokenizer, values, limit, mode)
            except ValueError as error:
                negatives.append(
                    {
                        "mode": mode,
                        "control": kind,
                        "rejected": True,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                )
            else:
                raise ValueError("required CPU rejection did not occur: " + kind)
    engine_qualification = ctx.previous_engine_qualification()
    legacy_protocol = retained(ctx.LEGACY_SOURCE / "prepared/PROTOCOL.json")
    retained(ctx.LEGACY_WORK / "TRAINING_ADMISSION.json")
    engine_identity = copy.deepcopy(legacy_protocol["training_engine_identity"])
    ctx.require(
        engine_identity["function_sha256"]
        == hashlib.sha256(
            inspect.getsource(
                fit.legacy.checkpoint_softmax.eager_checkpointed_softmax
            ).encode()
        ).hexdigest(),
        "qualified engine function changed",
    )
    budget = {}
    for mode in fit.MODES:
        schedule = [
            summaries[mode][index % len(records)]
            for index in range(fit.SETTINGS["steps"])
        ]
        budget[mode] = {
            "optimizer_updates": len(schedule),
            "outer_model_forwards": sum(
                row["model_forwards_per_step"] for row in schedule
            ),
            "outer_model_backwards": sum(
                row["model_backwards_per_step"] for row in schedule
            ),
            "supervised_target_positions": sum(
                row["supervised_positions_per_step"] for row in schedule
            ),
            "padded_positions": sum(
                row["padded_positions_per_step"] for row in schedule
            ),
            "unpadded_positions": sum(
                row["complete_input_tokens_per_forward"]
                * row["model_forwards_per_step"]
                for row in schedule
            ),
        }
    ctx.require(
        {
            key: value
            for key, value in budget[fit.MODES[0]].items()
            if key != "unpadded_positions"
        }
        == {
            key: value
            for key, value in budget[fit.MODES[1]].items()
            if key != "unpadded_positions"
        },
        "full actual planned training budget differs",
    )
    prepared = ctx.HERE / "prepared"
    prepared.mkdir(exist_ok=False)
    ctx.write(prepared / "DATASET.json", records)
    encoding = {
        "schema": "hepta.raw-function-layout-encoding.v1",
        "arms": summaries,
        "encoded_groups_digest": {
            mode: ctx.digest(value) for mode, value in groups.items()
        },
        "training_budget_per_arm": budget,
        "input_truncations": 0,
        "old_observed_actions_and_feedback_supervised": False,
        "target_format": "closed Python function plus native turn terminator",
        "shared_sequence_tokens": fit.SETTINGS["sequence_tokens"],
        "source_record_count": 4,
        "authenticated_users": 0,
    }
    ctx.write(prepared / "ENCODING.json", encoding)
    ctx.write(prepared / "INPUT_INDEX.json", files)
    ctx.write(
        prepared / "CPU_CONTROLS.json",
        {
            "status": "PASS_CPU_PREPARATION_ONLY",
            "negative_controls": negatives,
            "references": receipts,
            "actual_reference_native_children_reused": 4,
            "new_native_children": 0,
            "new_model_calls": 0,
            "new_training_updates": 0,
            "cuda_initialized": torch.cuda.is_initialized(),
            "weights_loaded": False,
        },
    )
    names = (
        "raw_context.py",
        "raw_sft.py",
        "prepare.py",
        "run_raw.py",
        "owner.py",
        "README.md",
        "prepared/DATASET.json",
        "prepared/ENCODING.json",
        "prepared/INPUT_INDEX.json",
        "prepared/CPU_CONTROLS.json",
    )
    protocol = {
        "schema": "hepta.raw-function-learning-protocol.v1",
        "prepared_at_ns": str(time.time_ns()),
        "builder_source_commit": source_commit,
        "primary_arm": "native_feedback",
        "control_arm": "document_evidence",
        "parent_model_digest": fit.PARENT,
        "parent_parameter_digest": fit.PARENT_PARAMETERS,
        "train_record_count": len(records),
        "train_records_digest": ctx.digest(records),
        "encoded_groups_digest": encoding["encoded_groups_digest"],
        "training_settings": fit.SETTINGS,
        "training_budget_per_arm": budget,
        "training_engine_identity": engine_identity,
        "previous_engine_qualification_sha256": engine_qualification,
        "previous_engine_qualification_scope": "exact unchanged eager/checkpoint engine and 3584 padded shape; earlier actual full 10 F/B gate, no claim that these new training records already ran",
        "candidate_files": {name: ctx.sha(ctx.HERE / name) for name in names},
        "original_input_files": files,
        "A_parent_reuse_files": parent_reuse,
        "information_match": "identical original A task, same actual P first raw-function response, exact actual native feedback, same verified maintainer function target",
        "layout_difference": "single user evidence document versus user-assistant-tool history; only the final maintainer target is supervised",
        "causal_hypothesis": "Matching the supervised function output format and learning from actual semantic failures may improve executable repairs; native feedback layout is compared with the same evidence in a document. This is a prospective hypothesis, not a guaranteed benefit.",
        "source_projects": list(ctx.PROJECTS),
        "authenticated_users": 0,
        "physical_compute_time_energy_equal": False,
        "inner_recomputation_counts_required_and_matched": True,
        "inference_policy": inference,
        "A_interface_source_commit": deployment["source_commit"],
        "A_protocol_sha256": ctx.FIXED["prepared/PROTOCOL.json"],
        "planned_new_generation_cap": 56,
        "new_generation_budget": {
            "A_current_policy_two_new_models": 16,
            "A_common_P_first_prefix_two_new_models": 8,
            "future_four_task_panel_current_policy_P_and_two_models": 24,
            "future_four_task_panel_common_P_prefix_two_models": 8,
        },
        "A_parent_calls_reused": 8,
        "two_calls_even_if_first_passes": True,
        "future_panel_contract": {
            "task_count": 4,
            "materials_chosen_and_published_only_after_both_actual_weights_frozen": True,
            "no_old_B_B2_B3_relabeling": True,
            "all_three_models_receive_same_complete_information_and_two_calls": True,
            "codec_and_native_oracle_qualification_before_new_calls": True,
            "separate_panel_source_and_protocol_release_required": True,
        },
        "decision_rule": {
            "candidate": "native_feedback",
            "A": "strictly more final successes than P, no lost P final success, preserve successful P second calls on the identical P first prefixes",
            "future_panel": "same strict final improvement and retention over actual P, with newly released material and frozen weights",
            "native_layout_mechanism": "native common-prefix success set strictly contains document common-prefix success set; report separately from primary candidate gate",
            "until_future_confirmation": "NoUpdate; A training/diagnostic improvements do not establish independent generalization",
            "previous_56_and_24_NoUpdate_unchanged": True,
        },
        "automatic_retry": False,
        "training_or_evaluation_B3_material_read": False,
        "native_adoption": False,
    }
    ctx.write(prepared / "PROTOCOL.json", protocol)
    ctx.require(
        not torch.cuda.is_initialized(), "CPU preparation unexpectedly initialized CUDA"
    )
    print(
        ctx.canonical(
            {
                "status": "PREPARED_ONLY_NO_TRAINING",
                "protocol_sha256": ctx.sha(prepared / "PROTOCOL.json"),
                "dataset_sha256": ctx.sha(prepared / "DATASET.json"),
                "encoding_sha256": ctx.sha(prepared / "ENCODING.json"),
                "cpu_controls_sha256": ctx.sha(prepared / "CPU_CONTROLS.json"),
                "budget": budget,
                "max_complete_input_tokens": max(
                    row["complete_input_tokens_per_forward"]
                    for rows in summaries.values()
                    for row in rows
                ),
                "new_model_calls": 0,
                "new_native_children": 0,
            }
        ).decode(),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    build(args.source_commit)
