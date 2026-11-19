"""Inspect completed A responses and prior A supervision without new execution."""

import argparse
import ast
import difflib
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def write(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def inspect(root, output):
    output.mkdir(exist_ok=False)
    inputs = {}

    def raw(path):
        path = Path(path)
        data = path.read_bytes()
        item = {"path": str(path), "bytes": len(data), "sha256": sha(data)}
        if str(path) in inputs and inputs[str(path)] != item:
            raise ValueError("input changed during inspection")
        inputs[str(path)] = item
        return data

    def read(path):
        return json.loads(raw(path))

    deployment = read(root / "DEPLOYMENT.json")
    protocol = read(root / "prepared/PROTOCOL.json")
    readout = read(root / "analysis-1/READOUT.json")
    if readout["status"] != "COMPLETE_ORIGINAL_24_RECONCILED":
        raise ValueError("complete original audit is required first")
    source = Path(deployment["source_directory"])
    if sha(raw(source / "replacement_codec.py")) != protocol["codec_sha256"]:
        raise ValueError("bound codec changed")
    sys.path.insert(0, str(source))
    codec = importlib.import_module("replacement_codec")
    if Path(codec.__file__).resolve() != (source / "replacement_codec.py").resolve():
        raise ValueError("wrong codec imported")
    tasks = read(root / "prepared/TASKS.json")
    records, pairs, model_outputs = [], [], {}
    for mode in protocol["planned_modes"]:
        for index, task in enumerate(tasks):
            before, binding = codec.source_binding(task["project_id"])
            if sha(before) != task["original_source_sha256"]:
                raise ValueError("bound original source changed")
            before_tree = ast.dump(ast.parse(before), include_attributes=False)
            pair_rows = []
            for attempt in (0, 1):
                folder = root / "results" / mode / str(index)
                produced = read(folder / ("OUTPUT-" + str(attempt) + ".json"))
                receipt = read(folder / ("VERIFICATION-" + str(attempt) + ".json"))
                feedback = read(folder / ("FEEDBACK-" + str(attempt) + ".json"))
                if sha(produced["answer"].encode()) != receipt[
                    "raw_answer_sha256"
                ] or feedback["verification_digest"] != sha(canonical(receipt)):
                    raise ValueError("original answer or feedback linkage changed")
                key = (mode, index, attempt)
                model_outputs[key] = produced["answer"]
                original = receipt.get("original_verification", {})
                row = {
                    "mode": mode,
                    "project_id": task["project_id"],
                    "task_index": index,
                    "attempt": attempt,
                    "stage": receipt["stage"],
                    "success": receipt["success"],
                    "reason": receipt.get("reason"),
                    "actual_native_child": receipt["actual_native_child"],
                    "raw_answer_sha256": receipt["raw_answer_sha256"],
                    "feedback_sha256": sha(feedback["content"].encode()),
                    "input_tokens": produced["input_tokens"],
                    "output_tokens": produced["output_tokens"],
                    "output_cap_hit": produced["hit_output_limit"],
                    "before_byte_equal": None,
                    "before_ast_equal": None,
                    "original_native_counts": {
                        key: original.get(key)
                        for key in ("tests", "failures", "errors", "skipped")
                    },
                    "original_failed_cases": [
                        case
                        for case in original.get("cases", [])
                        if case.get("failure") or case.get("error")
                    ],
                    "actual_raw_response": produced["answer"],
                }
                if receipt["actual_native_child"]:
                    patched = raw(
                        folder
                        / ("verify-" + str(attempt))
                        / "original-verifier/native/PATCHED_SOURCE.py"
                    )
                    row["before_byte_equal"] = patched == before
                    row["before_ast_equal"] = (
                        ast.dump(ast.parse(patched), include_attributes=False)
                        == before_tree
                    )
                    row["patched_source_sha256"] = sha(patched)
                    if not row["before_ast_equal"]:
                        row["original_to_executed_diff"] = "".join(
                            difflib.unified_diff(
                                before.decode().splitlines(keepends=True),
                                patched.decode().splitlines(keepends=True),
                                fromfile="bound-original-before",
                                tofile="actual-executed-model-source",
                            )
                        )
                records.append(row)
                pair_rows.append(row)
            pairs.append(
                {
                    "mode": mode,
                    "project_id": task["project_id"],
                    "first_and_second_raw_answers_identical": pair_rows[0][
                        "raw_answer_sha256"
                    ]
                    == pair_rows[1]["raw_answer_sha256"],
                    "first_success": pair_rows[0]["success"],
                    "second_success": pair_rows[1]["success"],
                    "second_received_actual_first_response_and_feedback": readout[
                        "actual_own_first_response_and_real_feedback_checked"
                    ],
                    "first_stage": pair_rows[0]["stage"],
                    "second_stage": pair_rows[1]["stage"],
                }
            )

    prior = Path(
        "/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b-checkpoint2/source/qualification/cell-upstream-layout-learning-20261118/prepared/DATASET.json"
    )
    prior_raw = raw(prior)
    if (
        sha(prior_raw)
        != "83d8e4c9294e9fd2250a9915db1c859acf607e053c29647bcf0dabcb94368bf3"
    ):
        raise ValueError("previous published A training data changed")
    data = json.loads(prior_raw)
    training_rows = []
    for row in data:
        target = row["final_answer"]
        parsed = json.loads(target)
        observed_feedback = json.loads(row["observed_feedback"])
        training_rows.append(
            {
                "record_id": row["record_id"],
                "project_id": row["project_id"],
                "target_sha256": sha(target.encode()),
                "supervised_target_is_JSON_edits": isinstance(parsed, dict)
                and set(parsed) == {"edits"},
                "supervised_target_starts_closed_python_block": target.startswith(
                    "```python\n"
                )
                and target.endswith("```"),
                "observed_feedback_stage": observed_feedback["stage"],
                "observed_success": row["observed_success"],
                "observed_action_supervised": row["observed_action_supervised"],
                "target_kind": row["target_kind"],
                "teacher_2_used_as_target": row["teacher_2_used_as_target"],
            }
        )
    if len(training_rows) != 8 or {row["project_id"] for row in training_rows} != {
        task["project_id"] for task in tasks
    }:
        raise ValueError("prior A supervision scope differs")
    native_rows = [row for row in records if row["actual_native_child"]]
    summary = {
        "schema": "hepta.replacement-A-observed-mechanism.v1",
        "created_at_ns": str(time.time_ns()),
        "execution_source_commit": deployment["source_commit"],
        "audit_readout_sha256": sha(raw(root / "analysis-1/READOUT.json")),
        "diagnostic_only_already_exposed_A": True,
        "new_model_calls": 0,
        "new_native_children": 0,
        "old_scores_and_NoUpdate_unchanged": True,
        "actual_original_calls": len(records),
        "actual_original_native_children": len(native_rows),
        "strict_successes": sum(row["success"] for row in records),
        "original_source_byte_identical_native_children": sum(
            row["before_byte_equal"] for row in native_rows
        ),
        "original_source_AST_identical_native_children": sum(
            row["before_ast_equal"] for row in native_rows
        ),
        "identical_first_second_answers": sum(
            pair["first_and_second_raw_answers_identical"] for pair in pairs
        ),
        "first_second_pair_count": len(pairs),
        "document_answers_identical_to_P": sum(
            model_outputs[("document_evidence", index, attempt)]
            == model_outputs[("P", index, attempt)]
            for index in range(4)
            for attempt in (0, 1)
        ),
        "native_answers_identical_to_P": sum(
            model_outputs[("native_feedback", index, attempt)]
            == model_outputs[("P", index, attempt)]
            for index in range(4)
            for attempt in (0, 1)
        ),
        "original_test_cases_across_children": sum(
            row["original_native_counts"]["tests"] for row in native_rows
        ),
        "original_test_failures_across_children": sum(
            row["original_native_counts"]["failures"] for row in native_rows
        ),
        "original_test_errors_across_children": sum(
            row["original_native_counts"]["errors"] for row in native_rows
        ),
        "original_test_skips_across_children": sum(
            row["original_native_counts"]["skipped"] for row in native_rows
        ),
        "per_case_counts_do_not_replace_strict_task_success": True,
        "output_caps_hit": sum(row["output_cap_hit"] for row in records),
        "previous_training_dataset_sha256": sha(prior_raw),
        "previous_training_rows": len(training_rows),
        "previous_JSON_edits_targets": sum(
            row["supervised_target_is_JSON_edits"] for row in training_rows
        ),
        "previous_closed_python_function_targets": sum(
            row["supervised_target_starts_closed_python_block"] for row in training_rows
        ),
        "previous_feedback_stage_counts": {
            stage: sum(row["observed_feedback_stage"] == stage for row in training_rows)
            for stage in sorted(
                {row["observed_feedback_stage"] for row in training_rows}
            )
        },
        "causal_interpretation": "Observed format and feedback distribution differences motivate a new matched A-only experiment; these observations do not establish that changing supervision will improve semantic repair or generalization.",
        "remaining_semantic_change": [
            row for row in records if row["before_ast_equal"] is False
        ],
        "admission_rejections": [
            row for row in records if not row["actual_native_child"]
        ],
    }
    write(output / "CALLS.json", records)
    write(output / "PAIRS.json", pairs)
    write(output / "PRIOR_SUPERVISION.json", training_rows)
    write(output / "MECHANISM.json", summary)
    write(
        output / "INPUT_INDEX.json",
        sorted(inputs.values(), key=lambda row: row["path"]),
    )
    print(
        json.dumps(
            {
                "summary": {
                    key: value
                    for key, value in summary.items()
                    if key not in ("remaining_semantic_change", "admission_rejections")
                },
                "mechanism_sha256": sha((output / "MECHANISM.json").read_bytes()),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inspect(args.root, args.output)
