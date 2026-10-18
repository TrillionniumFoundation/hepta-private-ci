#!/usr/bin/env python3
"""Encode declarative, unsealed paired inputs for the normal G entry.

This is material preparation, not a receipt, signature, clock or authority.
The actual G freezes the complete native plan after physical input measurement.
Fields and tags mirror paired_review_plan.rs and the existing archive codec.
"""

import json
import struct
import sys
from pathlib import Path

DOMAIN = b"hepta.eval.paired-supervised.review-plan-inputs.v1"
SCHEMAS = {
    "plan": "base_plan:base source_scope:scope source_records:list.record folds:list.fold unscored_source_records:list.digest tasks:list.task runtime:runtime policy:policy metrics:list.metric",
    "base": "plan_id:id claim_scope:claim candidate_id:id baseline_id:id objective_digest:digest dataset_digest:digest estimand_digest:digest metric_contracts:list.contract family_alpha_ppm:u32 simultaneous_comparisons:u32 folds:list.partition final_holdout_window_id:id final_holdout_digest:digest",
    "scope": "objective_digest:digest task_definition_digest:digest source_archive_digest:digest",
    "record": "source_file_digest:digest source_row_index:u64 source_record_digest:digest task_id:id dependency_ids:list.id",
    "fold": "fold_id:id training_records:list.digest holdout_records:list.digest training_windows:list.id holdout_windows:list.id model_digest:digest predictions_digest:digest",
    "partition": "fold_id:id training_principals:list.id training_episodes:list.id training_windows:list.id holdout_principals:list.id holdout_episodes:list.id holdout_windows:list.id model_digest:digest predictions_digest:digest",
    "contract": "metric_id:id direction:direction safety_floor:optional.q32",
    "task": "source_record_digest:digest candidate_request_id:id baseline_request_id:id candidate_input_digest:digest baseline_input_digest:digest",
    "runtime": "candidate_artifact_digest:digest deployed_baseline_digest:digest candidate_runtime_digest:digest baseline_runtime_digest:digest task_input_contract_digest:digest",
    "policy": "required_evidence_metrics:evidence output_alphabet:list.id assumptions_digest:digest minimum_independent_clusters:u64 maximum_abstain_ppm:u32 maximum_execution_window_micros:u64",
    "evidence": "execution_cost:id retention:id unlearning:id",
    "metric": "contract:contract role:role kind:kind",
}


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate input field")
        value[key] = item
    return value


def encode(kind, value):
    if kind in SCHEMAS:
        fields = [field.split(":") for field in SCHEMAS[kind].split()]
        if not isinstance(value, dict) or set(value) != {key for key, _ in fields}:
            raise ValueError(f"exact native {kind} fields required")
        return b"".join(encode(child, value[key]) for key, child in fields)
    if kind.startswith("list."):
        if not isinstance(value, list) or len(value) > 16384:
            raise ValueError("native list bound")
        return struct.pack(">I", len(value)) + b"".join(
            encode(kind[5:], row) for row in value
        )
    if kind.startswith("optional."):
        return b"\0" if value is None else b"\1" + encode(kind[9:], value)
    if kind in ("u32", "u64", "q32"):
        if type(value) is not int:
            raise ValueError("native integer, not bool/float, required")
        return struct.pack({"u32": ">I", "u64": ">Q", "q32": ">q"}[kind], value)
    if kind == "digest":
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
        ):
            raise ValueError("canonical digest required")
        return bytes.fromhex(value)
    if kind == "id":
        raw = value.encode("utf-8") if isinstance(value, str) else b""
        if not 1 <= len(raw) <= 128:
            raise ValueError("native identifier bound")
        return struct.pack(">I", len(raw)) + raw
    if kind in ("claim", "direction"):
        tags = {
            "claim": {"Qualification": 0, "SystemLongitudinal": 1},
            "direction": {"Maximize": 0, "Minimize": 1},
        }
        return bytes([tags[kind][value]])
    if kind in ("role", "kind"):
        variants = {
            "role": {
                "PrimarySuperiority": (0, "minimum_improvement:q32"),
                "NonInferiority": (1, "maximum_regression:q32"),
                "AbsoluteConstraint": (2, ""),
            },
            "kind": {
                "ClassificationAccuracy": (0, ""),
                "ExecutionLatencyMillis": (1, "maximum:q32"),
                "ObservedBounded": (2, "minimum:q32 maximum:q32"),
            },
        }
        if not isinstance(value, dict) or len(value) != 1:
            raise ValueError("one explicit native variant required")
        name, fields = next(iter(value.items()))
        tag, declarations = variants[kind][name]
        spec = [field.split(":") for field in declarations.split()]
        if not isinstance(fields, dict) or set(fields) != {key for key, _ in spec}:
            raise ValueError("exact native variant fields")
        return bytes([tag]) + b"".join(
            encode(child, fields[key]) for key, child in spec
        )
    raise ValueError("unsupported native input type")


def encode_inputs(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "inputs"}
        or value["schema"] != "hepta.eval.paired-supervised.declarative-inputs.v1"
    ):
        raise ValueError("explicit unsealed material schema required")
    result = DOMAIN + encode("plan", value["inputs"])
    if len(result) > 32 * 1024 * 1024:
        raise ValueError("native payload bound")
    return result


def main():
    if len(sys.argv) != 2:
        raise ValueError("usage: hepta_encode_paired_plan_inputs.py INPUT_JSON")
    raw = Path(sys.argv[1]).read_bytes()
    if len(raw) > 128 * 1024 * 1024:
        raise ValueError("declarative input bound")
    value = json.loads(raw, object_pairs_hook=unique_object)
    print(encode_inputs(value).hex())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, struct.error, OSError) as error:
        # No interpreter site hook, source values, keys or raw input are emitted.
        print(
            f"paired input preparation refused: {type(error).__name__}", file=sys.stderr
        )
        sys.exit(1)
