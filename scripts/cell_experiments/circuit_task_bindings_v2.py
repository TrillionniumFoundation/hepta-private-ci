"""Verify cached model, input, answer and semantic-execution receipt bindings."""

import copy
import hashlib
import math

from .composition_core import require, sha
from .data import digest as receipt_digest


MODEL_ORDER = ("specialist_numeric", "specialist_structured", "final_answer")


def _bound_panel(records, evaluations, expected_models, expected_panel_digest):
    require(
        sha(expected_panel_digest) and receipt_digest(records) == expected_panel_digest,
        "task panel digest differs",
    )
    require(
        type(records) is list and 0 < len(records) <= 16384,
        "bounded task records required",
    )
    require(
        type(expected_models) in (list, tuple)
        and len(expected_models) == len(set(expected_models)) == 3
        and all(sha(value) for value in expected_models),
        "three distinct frozen model digests required",
    )
    require(
        type(evaluations) in (list, tuple) and len(evaluations) == 3,
        "three ordered evaluation receipts required",
    )
    tasks = {record["task_id"]: record for record in records}
    require(len(tasks) == len(records), "duplicate task IDs are not independent rows")
    bound, upstream = [], []
    for slot, evaluation in enumerate(evaluations):
        require(
            evaluation.get("schema") == "hepta.repository-evaluation.v2"
            and evaluation.get("status") == "COMPLETE",
            "complete repository evaluation required",
        )
        require(
            evaluation.get("model_digest") == expected_models[slot],
            "evaluation model order differs",
        )
        evaluation_digest = receipt_digest(evaluation)
        observed = {row["task_id"]: row for row in evaluation["rows"]}
        require(
            len(observed)
            == len(evaluation["rows"])
            == evaluation.get("tasks")
            == len(tasks)
            and set(observed) == set(tasks),
            "evaluation task set differs",
        )
        first, calls, input_tokens, output_tokens = {}, 0, 0, 0
        for task_id, record in tasks.items():
            row = observed[task_id]
            require(
                all(
                    row.get(key) == record[key]
                    for key in ("record_id", "source_id", "lineage_id")
                ),
                "task provenance differs",
            )
            require(
                row.get("task_digest") == receipt_digest(record)
                and row.get("original_input_sha256")
                == receipt_digest(record["task"]["input"]),
                "evaluated original task differs",
            )
            require(
                type(row.get("steps")) is list and bool(row["steps"]),
                "actual first attempt required",
            )
            step = row["steps"][0]
            require(
                step.get("number") == 0
                and receipt_digest(
                    {
                        key: value
                        for key, value in step.items()
                        if key != "receipt_sha256"
                    }
                )
                == step.get("receipt_sha256"),
                "first-attempt receipt differs",
            )
            output, verification = step["output"], step.get("verification")
            raw_input = hashlib.sha256(record["task"]["input"].encode()).hexdigest()
            require(
                output.get("loaded_model_digest") == expected_models[slot]
                and output.get("input_sha256") == raw_input,
                "first-attempt model or prompt differs",
            )
            require(
                type(output.get("answer")) is str and isinstance(verification, dict),
                "actual answer and semantic receipt required",
            )
            payload = {
                key: value
                for key, value in verification.items()
                if key not in ("receipt_sha256", "success")
            }
            require(
                receipt_digest(payload) == verification.get("receipt_sha256"),
                "semantic receipt bytes differ",
            )
            spec = record["task"]["verifier"]
            require(
                verification.get("schema")
                == "hepta.cell-experiments.semantic-receipt.v1"
                and verification.get("record_id") == record["record_id"],
                "semantic task differs",
            )
            require(
                verification.get("input_sha256") == raw_input
                and verification.get("answer_sha256")
                == hashlib.sha256(output["answer"].encode()).hexdigest(),
                "semantic input or answer differs",
            )
            require(
                list(verification.get("verifier", []))
                == ["repo_patch", "1"]
                == [spec["name"], spec["version"]]
                and verification.get("parameters_sha256")
                == receipt_digest(spec["parameters"])
                and sha(verification.get("verifier_source_sha256")),
                "repository verifier binding differs",
            )
            result = verification["result"]
            execution = result.get("result") or {}
            count = execution.get("control_count")
            successful = bool(
                result.get("executed") is True
                and result.get("exit_code") == 0
                and execution.get("original_passed") is True
                and type(count) is int
                and count > 0
                and execution.get("controls_rejected") == count
            )
            require(
                type(verification.get("success")) is bool
                and verification["success"] == result.get("success") == successful,
                "semantic success differs from executed business checks",
            )
            require(
                row.get("first_attempt_success") == successful
                and step.get("executed") == bool(result.get("executed", False)),
                "attempt summary differs",
            )
            first[task_id] = {
                "model_slot": slot,
                "model_name": MODEL_ORDER[slot],
                "model_digest": expected_models[slot],
                "evaluation_digest": evaluation_digest,
                "task_id": task_id,
                "source_id": row["source_id"],
                "lineage_id": row["lineage_id"],
                "task_digest": row["task_digest"],
                "step_receipt_sha256": step["receipt_sha256"],
                "semantic_receipt_sha256": verification["receipt_sha256"],
                "output_digest": receipt_digest(output),
                "raw_answer": output["answer"],
                "semantic_receipt": copy.deepcopy(verification),
                "success": successful,
                "executed": step["executed"],
                "input_tokens": output["input_tokens"],
                "output_tokens": output["output_tokens"],
            }
            for attempt in row["steps"]:
                require(
                    attempt["output"].get("loaded_model_digest")
                    == expected_models[slot],
                    "later attempt model differs",
                )
                for key in ("input_tokens", "output_tokens"):
                    require(
                        type(attempt["output"].get(key)) is int
                        and attempt["output"][key] >= 0,
                        "bounded actual token counts required",
                    )
                calls += 1
                input_tokens += attempt["output"]["input_tokens"]
                output_tokens += attempt["output"]["output_tokens"]
        cost = evaluation["cost"]
        require(
            (
                cost.get("model_calls"),
                cost.get("input_tokens"),
                cost.get("output_tokens"),
            )
            == (calls, input_tokens, output_tokens),
            "upstream execution costs differ from actual rows",
        )
        require(
            evaluation.get("first_attempt_successes")
            == sum(row["success"] for row in first.values()),
            "first-attempt total differs",
        )
        for key in ("wall_seconds", "cpu_seconds"):
            require(
                type(cost.get(key)) in (int, float)
                and math.isfinite(cost[key])
                and cost[key] >= 0,
                "actual evaluation duration required",
            )
        bound.append(first)
        upstream.append(
            {
                "slot": slot,
                "model": MODEL_ORDER[slot],
                "evaluation_digest": evaluation_digest,
                "cost": copy.deepcopy(cost),
                "first_attempt_successes": sum(
                    row["success"] for row in first.values()
                ),
            }
        )
    return bound, upstream


def _bound_features(records, feature_rows):
    require(
        type(feature_rows) is list and len(feature_rows) == len(records),
        "one frozen feature row per task required",
    )
    features = {row["task_id"]: row for row in feature_rows}
    require(
        len(features) == len(records)
        and set(features) == {record["task_id"] for record in records},
        "feature task set differs",
    )
    bindings = {row.get("feature_binding_digest") for row in feature_rows}
    require(
        len(bindings) == 1 and sha(next(iter(bindings))),
        "one frozen feature encoder binding required",
    )
    for record in records:
        row = features[record["task_id"]]
        require(
            all(
                row.get(key) == record[key]
                for key in ("source_id", "lineage_id", "project_id")
            )
            and row.get("observation_digest")
            == receipt_digest(record["task"]["input"]),
            "feature provenance differs",
        )
        require(
            type(row.get("features")) is list
            and bool(row["features"])
            and all(
                type(value) in (int, float) and math.isfinite(value)
                for value in row["features"]
            ),
            "finite input features required",
        )
    return features
