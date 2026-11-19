"""Recompute the frozen layout decision from completed original receipts only."""

import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(
    "/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b-checkpoint2"
)
SOURCE = ROOT / "source/qualification/cell-upstream-layout-learning-20261118"
sys.path.insert(0, str(SOURCE))
ctx = importlib.import_module("layout_context")

EXPECTED_PROTOCOL = "c71f8348977e955b1d5b6b98e8780ff13188b88b141fad683efb6f08bb03814f"
MODES = ("P", "document_evidence", "native_feedback")
PARENT = "430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786"


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return ctx.data.digest(value)


def file_record(path):
    path = Path(path)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def write(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(ctx.data.canonical(value) + b"\n")


def verify_call(folder, attempt, task, messages, model, reused, feedback_fn):
    request_path = folder / ("REQUEST-" + str(attempt) + ".json")
    output_path = folder / ("OUTPUT-" + str(attempt) + ".json")
    receipt_path = folder / ("VERIFICATION-" + str(attempt) + ".json")
    feedback_path = folder / ("FEEDBACK-" + str(attempt) + ".json")
    request, output, receipt, feedback = map(
        read, (request_path, output_path, receipt_path, feedback_path)
    )
    require(
        request
        == {
            "record_id": task["record_id"],
            "task": {"input": task["task"]["input"], "messages": messages},
        },
        "actual request differs from frozen task/current prefix",
    )
    require(output["loaded_model_manifest_digest"] == model, "loaded model changed")
    require(
        output["input_truncated"] is False
        and output["maximum_new_tokens"] == 2048
        and output["input_tokens"] <= 8192
        and output["input_tokens"] + 2048 <= output["native_max_position_embeddings"]
        and output["output_tokens"] == len(output["output_token_ids"])
        and 0 < output["output_tokens"] <= 2048,
        "actual call violates complete-context or output budget",
    )
    require(
        hashlib.sha256(output["answer"].encode()).hexdigest()
        == receipt["answer_sha256"],
        "verification did not bind actual raw answer",
    )
    require(
        feedback["verification_digest"] == digest(receipt)
        and feedback["content"] == feedback_fn(receipt),
        "next feedback differs from actual immutable verifier receipt",
    )
    if not reused:
        require(
            (folder / ("GENERATION_STARTED-" + str(attempt) + ".json")).is_file(),
            "missing actual generation-start receipt",
        )
    return (
        {
            "record_id": task["record_id"],
            "project_id": task["project_id"],
            "attempt": attempt,
            "success": receipt["success"],
            "actual_native_child": receipt["actual_native_child"],
            "stage": receipt["stage"],
            "admission_reason": receipt.get("reason"),
            "input_tokens": output["input_tokens"],
            "output_tokens": output["output_tokens"],
            "hit_output_limit": output["hit_output_limit"],
            "input_truncated": output["input_truncated"],
            "generation_wall_seconds": output["wall_seconds"],
            "verification_wall_seconds": receipt.get(
                "verification_wall_seconds", receipt.get("wall_seconds")
            ),
            "model_digest": model,
            "started_at_ns": str(output["started_at_ns"]),
            "completed_at_ns": str(output["completed_at_ns"]),
            "effective_policy_digest": output["effective_policy_digest"],
            "generation_config_sha256": output["generation_config_sha256"],
            "reused_not_new_generation": reused,
            "files": {
                name: file_record(path)
                for name, path in (
                    ("request", request_path),
                    ("output", output_path),
                    ("verification", receipt_path),
                    ("feedback", feedback_path),
                )
            },
        },
        output,
        feedback,
    )


def metrics(pairs):
    first = {i for i, pair in enumerate(pairs) if pair[0]["success"]}
    final = {i for i, pair in enumerate(pairs) if pair[1]["success"]}
    return {
        "tasks": len(pairs),
        "first_success": len(first),
        "final_success": len(final),
        "any_success": len(first | final),
        "fail_to_pass": len(final - first),
        "pass_to_fail": len(first - final),
        "recovery_opportunities": len(pairs) - len(first),
        "preservation_opportunities": len(first),
        "first_success_set": sorted(first),
        "final_success_set": sorted(final),
        "recovered_task_set": sorted(final - first),
        "regressed_task_set": sorted(first - final),
    }


def main(binding_path):
    require(
        sha(SOURCE / "prepared/PROTOCOL.json") == EXPECTED_PROTOCOL, "protocol changed"
    )
    protocol = read(SOURCE / "prepared/PROTOCOL.json")
    for name, expected in protocol["candidate_files"].items():
        require(
            sha(SOURCE / name) == expected, "candidate source/data changed: " + name
        )
    for name, expected in protocol["A_parent_reuse_files"].items():
        require(sha(name) == expected, "precommitted A reuse changed: " + name)
    frozen_path = ROOT / "retained/WEIGHTS_FROZEN.json"
    frozen = read(frozen_path)
    require(
        frozen["status"] == "MATCHED_AND_WEIGHTS_FROZEN", "complete real fits required"
    )
    owners = {}
    for phase in ("training", "evaluation_A", "evaluation_B3"):
        path = ROOT / ("owned-" + phase + "-1") / "COMPLETE.json"
        owner = read(path)
        require(
            owner["status"] == "COMPLETE"
            and all(
                r["wait_returncode"] == 0 and not r["timed_out"]
                for r in owner["stage_exits"]
            ),
            "original owner did not complete: " + phase,
        )
        owners[phase] = {"file": file_record(path), "value": owner}
    binding = read(binding_path)
    require(
        binding["weights_frozen_sha256"] == sha(frozen_path)
        and int(binding["released_at_ns"]) > frozen["created_at_ns"],
        "B3 release does not follow frozen actual weights",
    )
    for name in ("tasks", "protocol", "loader"):
        require(
            sha(binding[name + "_path"]) == protocol["B3_commitment"][name + "_sha256"],
            "released B3 differs from original precommitment",
        )
    require(
        sha(binding["release_path"]) == binding["release_sha256"], "release changed"
    )
    a_verifier, _, a_tasks, _ = ctx.originals()
    b_verifier = ctx.load(
        "layout_readout_b3_native",
        Path(binding["loader_path"]),
        protocol["B3_commitment"]["loader_sha256"],
    )
    panels = {
        "A": (a_tasks, a_verifier),
        "B3": (read(binding["tasks_path"]), b_verifier),
    }
    model_ids = {"P": PARENT}
    training = {}
    for mode in MODES[1:]:
        folder = ROOT / "retained" / mode
        manifest = read(folder / "manifest.json")
        fit = read(folder / "TRAINING.json")
        require(
            sha(folder / "manifest.json") == frozen["arms"][mode]["manifest_sha256"]
            and sha(folder / "TRAINING.json") == frozen["arms"][mode]["training_sha256"]
            and digest(manifest) == frozen["arms"][mode]["model_digest"]
            and fit["steps"] == 32
            and fit["status"] == "COMPLETE",
            "actual training or frozen model differs",
        )
        model_ids[mode] = digest(manifest)
        training[mode] = {
            "manifest": file_record(folder / "manifest.json"),
            "result": fit,
        }
    calls, scores, paired, result_files = [], {}, {}, []
    for panel, (tasks, verifier) in panels.items():
        require(len(tasks) == 4, "four fixed tasks required")
        scores[panel], paired[panel] = {}, {}
        parents = []
        for mode in MODES:
            reused = panel == "A" and mode == "P"
            stage = ROOT / "evaluation" / panel / mode
            base = ctx.COLLECTION / "results/P" if reused else stage / "current"
            pairs = []
            for index, task in enumerate(tasks):
                messages = copy.deepcopy(task["task"]["messages"])
                pair = []
                for attempt in (0, 1):
                    row, output, feedback = verify_call(
                        base / str(index),
                        attempt,
                        task,
                        messages,
                        model_ids[mode],
                        reused,
                        verifier.feedback,
                    )
                    if panel == "B3":
                        require(
                            int(row["started_at_ns"]) > int(binding["released_at_ns"]),
                            "B3 call predates release",
                        )
                    row.update(panel=panel, mode=mode, kind="current", task_index=index)
                    calls.append(row)
                    pair.append(row)
                    messages += [
                        {"role": "assistant", "content": output["answer"]},
                        {"role": "tool", "content": feedback["content"]},
                    ]
                pairs.append(pair)
            scores[panel][mode] = {"current": metrics(pairs)}
            if mode == "P":
                parents = pairs
                common = [pair[1] for pair in pairs]
            else:
                common = []
                for index, task in enumerate(tasks):
                    parent_folder = (
                        ctx.COLLECTION / "results/P"
                        if panel == "A"
                        else ROOT / "evaluation/B3/P/current"
                    ) / str(index)
                    first = read(parent_folder / "OUTPUT-0.json")
                    feedback = read(parent_folder / "FEEDBACK-0.json")
                    messages = copy.deepcopy(task["task"]["messages"]) + [
                        {"role": "assistant", "content": first["answer"]},
                        {"role": "tool", "content": feedback["content"]},
                    ]
                    folder = stage / "common_P_prefix" / str(index)
                    require(
                        read(folder / "REQUEST-0.json")
                        == read(parent_folder / "REQUEST-1.json"),
                        "common-prefix request not exactly parent second request",
                    )
                    row, _, _ = verify_call(
                        folder,
                        0,
                        task,
                        messages,
                        model_ids[mode],
                        False,
                        verifier.feedback,
                    )
                    if panel == "B3":
                        require(
                            int(row["started_at_ns"]) > int(binding["released_at_ns"]),
                            "B3 common-prefix call predates release",
                        )
                    row.update(
                        panel=panel, mode=mode, kind="common_P_prefix", task_index=index
                    )
                    calls.append(row)
                    common.append(row)
            success_set = {i for i, row in enumerate(common) if row["success"]}
            parent_first = {i for i, pair in enumerate(parents) if pair[0]["success"]}
            parent_second = {i for i, pair in enumerate(parents) if pair[1]["success"]}
            scores[panel][mode]["common_P_prefix"] = {
                "success": len(success_set),
                "success_set": sorted(success_set),
                "recovery_success": len(success_set - parent_first),
                "recovery_opportunities": 4 - len(parent_first),
                "preserved_first_success": len(success_set & parent_first),
                "preservation_opportunities": len(parent_first),
                "preserved_parent_second_success": len(success_set & parent_second),
                "parent_second_success_opportunities": len(parent_second),
                "lost_parent_second_success_set": sorted(parent_second - success_set),
                "parent_second_preservation_vacuous": not parent_second,
            }
            paired[panel][mode] = [
                {
                    "task_index": i,
                    "project_id": tasks[i]["project_id"],
                    "first": pairs[i][0]["success"],
                    "final": pairs[i][1]["success"],
                    "common_P_prefix": common[i]["success"],
                }
                for i in range(4)
            ]
            if not reused:
                actual = read(stage / "RESULT.json")
                stage_calls = [
                    r for r in calls if r["panel"] == panel and r["mode"] == mode
                ]
                count = 8 if mode == "P" else 12
                require(
                    actual["status"] == "COMPLETE"
                    and actual["actual_model_calls"] == len(stage_calls) == count
                    and len(list(stage.glob("*/*/GENERATION_STARTED-*.json"))) == count,
                    "complete bounded actual generation count differs",
                )
                for key in ("input_tokens", "output_tokens"):
                    require(
                        actual["cost"][key] == sum(r[key] for r in stage_calls),
                        "reported token totals differ",
                    )
                indexed = {
                    (r["kind"], r["task_index"], r["attempt"]): r
                    for r in actual["rows"]
                }
                for row in stage_calls:
                    indexed_row = indexed[
                        (row["kind"], row["task_index"], row["attempt"])
                    ]
                    for key, record in row["files"].items():
                        if key != "feedback":
                            require(
                                indexed_row[key + "_sha256"] == record["sha256"],
                                "reported original call digest differs",
                            )
                    require(
                        indexed_row["success"] == row["success"],
                        "reported strict score differs",
                    )
                result_files.append(
                    {"file": file_record(stage / "RESULT.json"), "cost": actual["cost"]}
                )
    new_calls = [row for row in calls if not row["reused_not_new_generation"]]
    require(
        len(new_calls) == 56 and len(calls) == 64,
        "56 new plus eight reused calls required",
    )
    require(
        {r["generation_config_sha256"] for r in calls}
        == {protocol["inference_policy"]["generation_config_sha256"]},
        "generation policy differs across arms",
    )
    decision = {}
    mechanism = {}
    for panel in panels:
        p = set(scores[panel]["P"]["current"]["final_success_set"])
        n = set(scores[panel]["native_feedback"]["current"]["final_success_set"])
        lost_common = scores[panel]["native_feedback"]["common_P_prefix"][
            "lost_parent_second_success_set"
        ]
        decision[panel] = {
            "native_final_strictly_more_than_P": len(n) > len(p),
            "lost_P_final_success_set": sorted(p - n),
            "lost_P_second_on_common_prefix_set": lost_common,
            "passed": len(n) > len(p) and not (p - n) and not lost_common,
        }
        native_common = set(
            scores[panel]["native_feedback"]["common_P_prefix"]["success_set"]
        )
        document_common = set(
            scores[panel]["document_evidence"]["common_P_prefix"]["success_set"]
        )
        mechanism[panel] = {
            "native_common_success_set_strictly_contains_document": native_common
            > document_common,
            "native_only": sorted(native_common - document_common),
            "document_only": sorted(document_common - native_common),
        }
    passed = all(row["passed"] for row in decision.values())
    output = ROOT / "analysis-1"
    output.mkdir(exist_ok=False)
    readout = {
        "schema": "hepta.upstream-layout-original-receipt-readout.v1",
        "created_at_ns": time.time_ns(),
        "execution_source_commit": "78099aa6af4c70c00f26cb11888e20aa59510014",
        "protocol_sha256": EXPECTED_PROTOCOL,
        "weights_frozen": file_record(frozen_path),
        "binding": file_record(binding_path),
        "decision_rule_unchanged": protocol["decision_rule"],
        "designated_primary": "native_feedback",
        "control": "document_evidence",
        "research_decision": "ACCEPT_NARROW_RESEARCH_CANDIDATE"
        if passed
        else "NoUpdate",
        "decision_checks": decision,
        "scores": scores,
        "common_prefix_mechanism": mechanism,
        "training": training,
        "owners": owners,
        "evaluation_stage_costs": result_files,
        "new_generation_calls": len(new_calls),
        "reused_generation_calls": len(calls) - len(new_calls),
        "new_input_tokens": sum(r["input_tokens"] for r in new_calls),
        "new_output_tokens": sum(r["output_tokens"] for r in new_calls),
        "native_children_new_evaluation": sum(
            r["actual_native_child"] for r in new_calls
        ),
        "output_limit_hits": sum(r["hit_output_limit"] for r in new_calls),
        "strict_original_receipts_recomputed_without_model_or_verifier_calls": True,
        "small_development_mechanism_result_only": True,
        "authenticated_users": 0,
        "authenticated_external_custody": False,
        "base_pretraining_contamination_excluded": False,
        "old_NoUpdate_decisions_unchanged": True,
        "native_adoption": False,
        "E1_full_retrieval_and_cost_controls_closed": False,
        "E3_teacher_complementarity_closed": False,
        "E5_growth_curves_closed": False,
        "full_system_cost_known": False,
        "gpu_energy_joules": None,
        "network_energy_joules": None,
        "monetary_cost": None,
        "nested_windows_are_not_additive": True,
    }
    write(output / "CALLS.json", calls)
    write(output / "PAIRED_TASKS.json", paired)
    write(output / "READOUT.json", readout)
    print(
        json.dumps(
            {
                "path": str(output),
                "readout_sha256": sha(output / "READOUT.json"),
                "calls_sha256": sha(output / "CALLS.json"),
                "paired_sha256": sha(output / "PAIRED_TASKS.json"),
                "research_decision": readout["research_decision"],
                "scores": scores,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b3-binding", type=Path, required=True)
    arguments = parser.parse_args()
    main(arguments.b3_binding)
