"""Build the eight fixed A supervision records without model inference or new tests."""

import argparse
import copy
import importlib
import time

import layout_context as ctx

layout = importlib.import_module("layout_sft")


def build(source_commit):
    native, parent, tasks, inference = ctx.originals()
    layout.require(
        tuple(task["project_id"] for task in tasks) == ctx.PROJECTS, "fixed A order"
    )
    layout.require(ctx.data.digest(parent) == layout.PARENT, "fixed actual parent")
    records, input_files = [], {}

    def retained(path):
        path = path.resolve(strict=True)
        path.relative_to(ctx.COLLECTION)
        input_files[str(path)] = ctx.sha(path)
        return ctx.read(path)

    for index, task in enumerate(tasks):
        oracle_path = (
            ctx.COLLECTION
            / "preparation-1/sandbox-preflight"
            / str(index)
            / "ORACLE_ACTION.json"
        )
        final_answer = native.canonical(retained(oracle_path)).decode()
        proof_path = oracle_path.parent / "after/RESULT.json"
        proof = retained(proof_path)
        candidate, _ = native.admit(task["project_id"], final_answer)
        _, folder = native.source(task["project_id"])
        layout.require(
            candidate == (folder / "after" / task["source_path"]).read_bytes(),
            "original maintainer bytes required",
        )
        layout.require(
            proof["success"]
            and proof["actual_native_child"]
            and proof["patched_source_sha256"] == native.sha(candidate)
            and proof["original_test_sha256"] == task["original_tests_sha256"],
            "real original reference receipt required",
        )
        for actor in ("P", "C"):
            folder = ctx.COLLECTION / "results" / actor / str(index)
            output_path, receipt_path, feedback_path = (
                folder / "OUTPUT-0.json",
                folder / "VERIFICATION-0.json",
                folder / "FEEDBACK-0.json",
            )
            output, receipt, feedback = (
                retained(path) for path in (output_path, receipt_path, feedback_path)
            )
            layout.require(
                output["loaded_model_manifest_digest"]
                == inference["model_digests"][actor],
                "actual first actor identity differs",
            )
            layout.require(
                receipt["answer_sha256"] == native.sha(output["answer"].encode())
                and feedback["verification_digest"]
                == native.sha(native.canonical(receipt))
                and feedback["content"] == native.feedback(receipt),
                "bound actual feedback",
            )
            record = {
                "record_id": task["record_id"] + ":" + actor + ":first",
                "task_id": task["task_id"],
                "project_id": task["project_id"],
                "source_path": task["source_path"],
                "source_index": index,
                "original_source_sha256": task["original_source_sha256"],
                "original_tests_sha256": task["original_tests_sha256"],
                "split": "train",
                "authorization": copy.deepcopy(task["authorization"]),
                "task": copy.deepcopy(task["task"]),
                "observed_actor": actor,
                "observed_answer": output["answer"],
                "observed_feedback": feedback["content"],
                "actual_observed_attempt": 0,
                "observed_success": receipt["success"],
                "observed_output_sha256": ctx.sha(output_path),
                "observed_verification_sha256": ctx.sha(receipt_path),
                "observed_feedback_sha256": ctx.sha(feedback_path),
                "reference_receipt_sha256": ctx.sha(proof_path),
                "final_answer": final_answer,
                "target_kind": "exact_original_upstream_maintainer_repair",
                "observed_action_supervised": False,
                "teacher_2_used_as_target": False,
            }
            record["information_digest"] = layout.information(record)
            records.append(record)
    parent_reuse_files = {}
    for index in range(4):
        for attempt in (0, 1):
            for kind in ("REQUEST", "OUTPUT", "VERIFICATION", "FEEDBACK"):
                path = (
                    ctx.COLLECTION
                    / "results/P"
                    / str(index)
                    / (kind + "-" + str(attempt) + ".json")
                )
                retained(path)
                parent_reuse_files[str(path)] = input_files[str(path)]
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        str(ctx.ARTIFACT / parent["runtime"]["base_directory"]),
        local_files_only=True,
        trust_remote_code=False,
    )
    layout.require(
        layout.chat_protocol.template_digest(tokenizer.chat_template)
        == parent["runtime"]["chat_template_sha256"],
        "fixed tokenizer template",
    )
    groups = {
        mode: layout.encode_groups(
            tokenizer, records, layout.SETTINGS["sequence_tokens"], mode
        )
        for mode in layout.MODES
    }
    summaries = {}
    for mode, values in groups.items():
        summaries[mode] = []
        for index, parts in enumerate(values):
            target_ids = [
                value for part in parts for value in part["labels"] if value != -100
            ]
            summaries[mode].append(
                {
                    "record_id": records[index]["record_id"],
                    "information_digest": records[index]["information_digest"],
                    "encoded_group_digest": ctx.data.digest(parts),
                    "target_ids_digest": ctx.data.digest(target_ids),
                    "model_forwards_per_step": len(parts),
                    "model_backwards_per_step": len(parts),
                    "full_input_tokens_per_forward": len(parts[0]["input_ids"]),
                    "head_positions_per_step": len(target_ids),
                    "supervised_positions_per_step": len(target_ids),
                    "padded_positions_per_step": layout.SETTINGS["sequence_tokens"]
                    * len(parts),
                }
            )
    match_keys = (
        "record_id",
        "information_digest",
        "target_ids_digest",
        "model_forwards_per_step",
        "model_backwards_per_step",
        "head_positions_per_step",
        "supervised_positions_per_step",
        "padded_positions_per_step",
    )
    for left, right in zip(summaries[layout.MODES[0]], summaries[layout.MODES[1]]):
        layout.require(
            {key: left[key] for key in match_keys}
            == {key: right[key] for key in match_keys},
            "information, targets or padded model work differs",
        )
    calibration_index = max(
        range(8),
        key=lambda i: max(len(groups[m][i][0]["input_ids"]) for m in layout.MODES),
    )
    prepared = ctx.HERE / "prepared"
    prepared.mkdir(exist_ok=False)
    ctx.write(prepared / "DATASET.json", records)
    encoding = {
        "schema": "hepta.upstream-layout-encoding.v1",
        "arms": summaries,
        "encoded_groups_digest": {
            mode: ctx.data.digest(value) for mode, value in groups.items()
        },
        "tokenizer_template_sha256": parent["runtime"]["chat_template_sha256"],
        "input_truncations": 0,
        "calibration_index": calibration_index,
        "calibration_selection": "largest complete A encoded input; no model outcome used",
        "supervised_target": "only verified original maintainer repair plus native message terminator",
        "prior_failed_actions_and_tool_feedback_supervised": False,
    }
    ctx.write(prepared / "ENCODING.json", encoding)
    ctx.write(prepared / "INPUT_INDEX.json", input_files)
    names = (
        "layout_sft.py",
        "layout_context.py",
        "build_dataset.py",
        "run_layout.py",
        "owner.py",
        "test_layout_sft.py",
        "README.md",
        "prepared/DATASET.json",
        "prepared/ENCODING.json",
        "prepared/INPUT_INDEX.json",
    )
    prior_root = ctx.WORK.parent / "hepta-upstream-layout-learning-20261118-2e9b"
    prior_failure = prior_root / "retained/calibration/FAILED.json"
    prior_exit = prior_root / "owned-training-1/calibration/EXIT.json"
    layout.require(
        ctx.sha(prior_failure)
        == "1a30a38f05d36d0a276e18d1dddb6181cc6933c0df0362c38f30ae1e6205d6c1"
        and ctx.sha(prior_exit)
        == "b8b4ebdd3b27193564c535ba732f209fbdc676f2b0bdff36692055147ae30f36",
        "original failed calibration must remain retained",
    )
    allocator_proof = ctx.WORK / "preparation/allocator-capability/RESULT.json"
    second_failure = (
        ctx.WORK.parent
        / "hepta-upstream-layout-learning-20261118-2e9b-3584/retained/calibration/FAILED.json"
    )
    layout.require(
        ctx.sha(allocator_proof)
        == "356db0b16048160e723b40e11f34c06e455634e3881282ee79160e5c58259aa2"
        and ctx.sha(second_failure)
        == "d3ccfdea6d8eb895d0159906e58d1e8867be127424a8395621d18757ba6255ff",
        "actual allocator control or second failure changed",
    )
    protocol = {
        "allocator_revision": {
            "configuration": "expandable_segments:True",
            "backend": "native",
            "scope": "explicit child-process environment only; memory cap remains 0.70; no daemon, driver, permissions or shared environment modified",
            "real_capability_receipt_sha256": ctx.sha(allocator_proof),
            "real_capability_probe_bytes": 8388608,
            "real_capability_model_calls": 0,
            "documentation": "https://docs.pytorch.org/docs/2.9/notes/cuda.html",
            "second_failure_source": "8f5835080b7fa4522cc3a675b071cc8e26d81b23",
            "second_failure_sha256": ctx.sha(second_failure),
            "second_failure_attempted_forwards": 1,
            "second_failure_completed_forwards": 0,
            "second_failure_backward_calls": 0,
            "second_failure_optimizer_updates": 0,
            "second_failure_generation_calls": 0,
            "second_failure_cold_load_seconds": 31.242553954012692,
        },
        "prior_failed_calibration": {
            "source_commit": "a764cca4e303f8acd10bf62629a3fc63a7cbb276",
            "job_id": "1a1f011ca61-ffbe-6ec",
            "failure_path": str(prior_failure),
            "failure_sha256": ctx.sha(prior_failure),
            "owner_exit_sha256": ctx.sha(prior_exit),
            "optimizer_updates": 0,
            "generation_calls": 0,
            "actual_model_computation": "real P cold load and parameter verification; at least one attempted eager forward; exact completed F/B counts unknown without old chunk events",
            "costs_retained": True,
            "old_source_and_output_overwritten": False,
        },
        "padding_revision": "4096 to 3584 = ceil(3471/128)*128, after real OOM; removes only masked padding; full evidence and identical targets retained",
        "partial_compute_accounting": "durable start/complete events for every real selected-head forward and backward",
        "schema": "hepta.upstream-layout-protocol.v1",
        "prepared_at_ns": time.time_ns(),
        "builder_source_commit": source_commit,
        "primary_arm": "native_feedback",
        "control_arm": "document_evidence",
        "parent_model_digest": layout.PARENT,
        "parent_parameter_digest": layout.PARENT_PARAMETERS,
        "parent_manifest_sha256": ctx.PARENT_FILE_SHA,
        "train_records_digest": ctx.data.digest(records),
        "train_record_count": len(records),
        "encoded_groups_digest": encoding["encoded_groups_digest"],
        "training_settings": layout.SETTINGS,
        "candidate_files": {name: ctx.sha(ctx.HERE / name) for name in names},
        "original_input_files": input_files,
        "calibration_index": calibration_index,
        "information_match": "same original task, actual first P/C answer, exact actual feedback, identical verified maintainer target",
        "layout_difference": "single user evidence document versus actual user-assistant-tool turns; native tool wire stays original labeled user observation",
        "compute_match": "same P tensors, empty AdamW, 32 updates, example order, target tokens, selected head positions, full padded 3584-token forwards/backwards",
        "unpadded_token_counts_can_differ": True,
        "physical_compute_time_energy_equal": False,
        "target_partition": "at most 256 selected head positions per full causal forward/backward; weighted target-count mean; no token truncation",
        "calibration": {
            "actual_forward_backward_per_arm": "one fixed largest A group",
            "optimizer_updates": 0,
            "automatic_retry": False,
        },
        "source_projects": list(ctx.PROJECTS),
        "authenticated_users": 0,
        "training_material_scope": "authorized public historical maintainer material; actual current-student failures are masked observations",
        "inference_policy": inference,
        "A_tasks_sha256": ctx.TASKS_SHA,
        "A_parent_reuse_files": parent_reuse_files,
        "collection_policy_source_sha256": ctx.POLICY_SHA,
        "native_verifier_sha256": ctx.NATIVE_SHA,
        "new_model_call_cap": 56,
        "new_model_calls": {
            "A_current_policy": 16,
            "A_common_original_P_prefix": 8,
            "B3_current_policy_including_P": 24,
            "B3_common_new_P_prefix": 8,
        },
        "reused_calls": {
            "A_parent_original_first_and_second": 8,
            "B3_parent_second_also_common_prefix_baseline": 4,
        },
        "two_calls_even_if_first_succeeds": True,
        "common_prefix_rule": "all four fixed tasks, original P first answer and exact feedback; parent second is reused, not counted as a new call",
        "B3_commitment": {
            "commit": "be30b06e13c11c44fb2821edfbd0383a8e28eb05",
            "commitment_sha256": "6714c2edae8185b23fed1ca4a81fc026fc09680adb4935969ea0aaa717bdf376",
            "tasks_sha256": "8ac4ecffb705f819b57b6d03aa1faff7808d9bb9f8eaff97006800cfc5861a15",
            "protocol_sha256": "95f3e4d82ea78721e360d9928530c9c60b841a1976cb4a6bc817d514aeb13225",
            "loader_sha256": "90c1ff7130ad20f775fdeb926703bb9cc8f0c3c83bc36da4bb66fa294e587109",
            "record_count": 4,
            "release_after_both_weights_frozen": True,
        },
        "B3_read_before_weights_frozen": False,
        "decision_rule": {
            "designated_candidate": "native_feedback",
            "A": "strictly more final successes than original P; no lost P final successes; preserve all successful original P second calls on identical first prefixes",
            "B3": "strictly more final successes than actual P; no lost P final successes; preserve all successful P second calls on identical first prefixes",
            "accept": "both A and B3 rules pass, complete exact source/model/runtime/receipts, otherwise NoUpdate and retain original P",
            "native_unique_mechanism": "separate claim only if native common-prefix success set strictly contains document success set; report A and B3 separately",
            "scope": "small development mechanism result; not authenticated independent confirmation, adoption, E5 curves or complete E1 controls",
        },
        "old_NoUpdate_decisions_unchanged": True,
        "native_adoption": False,
        "cost_scope": "all preparation, calibration, complete and failed training, cold loads, inference, verification and reuses; GPU/network/money unknown; any RAPL totals are whole-host windows",
    }
    ctx.write(prepared / "PROTOCOL.json", protocol)
    result = {
        "status": "PREPARED",
        "created_at_ns": time.time_ns(),
        "protocol_sha256": ctx.sha(prepared / "PROTOCOL.json"),
        "dataset_sha256": ctx.sha(prepared / "DATASET.json"),
        "encoding_sha256": ctx.sha(prepared / "ENCODING.json"),
        "train_records_digest": protocol["train_records_digest"],
        "encoded_groups_digest": protocol["encoded_groups_digest"],
        "calibration_index": calibration_index,
        "encoding": summaries,
        "model_generation_calls": 0,
        "native_test_executions": 0,
        "training_updates": 0,
        "B3_content_read": False,
    }
    ctx.write(ctx.WORK / "preparation/PREPARED.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    print(
        ctx.data.canonical(build(parser.parse_args().source_commit)).decode(),
        flush=True,
    )
