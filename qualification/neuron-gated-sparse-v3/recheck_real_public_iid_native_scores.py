#!/usr/bin/env python3
"""Independent *post-seal* static BANKING77 Q24 score recomputation.

Reconstruct the immutable original official heldout labels in a new process,
after physical Q24 candidate training and native execution are over.
All 1024 public label-free prediction records are SHA-bound to model identities.
This does not independently sign evaluation custody, attest pretrained weights,
compare a selected V1 baseline, or establish future/retention NDU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from real_encoder_q24_snapshot_gate import read, unique_json
from real_public_iid_q24_inputs import (
    read_original_public_inputs, verify_local_original_source,
)

SCHEMA = "hepta.neuron.independent-public-iid-q24-heldout-recheck.v1"
ARMS = ("v2", "v3", "ssm", "min_gru")
BUDGETS = (8192, 32768)
# Independent, immutable native Rust byte-profile admissions for F32 Adapter/
# Head and I64 Q24 temporal tensor payload; no Torch, zero-template planner
# import, or reviewer-side learning code may redefine these physical limits.
# (private width, physically realized parameter count, file bytes)
REGISTERED_BYTE_GEOMETRY = {
    (8192, "v2"): (54, 1891, 8148),
    (8192, "v3"): (45, 1711, 8172),
    (8192, "ssm"): (47, 1740, 8052),
    (8192, "min_gru"): (38, 1559, 8156),
    (32768, "v2"): (224, 7841, 32644),
    (32768, "v3"): (191, 7259, 32716),
    (32768, "ssm"): (201, 7438, 32708),
    (32768, "min_gru"): (166, 6807, 32756),
}
SHA_HEX = frozenset("0123456789abcdef")
MAX_BYTES = 2_000_000


class Rejected(ValueError):
    pass


def need(condition: bool, why: str) -> None:
    if not condition:
        raise Rejected(why)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def hex_digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in SHA_HEX for c in value)


def independent_record_bytes(value: dict) -> bytes:
    """Versioned canonical JSON defined by the reviewer, not the scorer."""
    need(type(value) is dict, "independent public record must be an object")
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def independent_binary_metrics(truth: list[int], outputs: list[dict]) -> dict:
    """Independent 8-positive/24-negative delivered confusion evaluation.

    Deliberately does not import the trainer/scorer's bin_metrics. An error
    in the original score calculation must be detectable here.
    """
    need(type(truth) is list and type(outputs) is list
         and len(truth) == len(outputs) == 32
         and all(type(y) is int and y in (0, 1) for y in truth)
         and sum(truth) == 8, "independent original heldout denominator is invalid")
    tp = tn = fp = fn = pos_abstain = neg_abstain = 0
    for gold, prediction in zip(truth, outputs, strict=True):
        need(type(prediction) is dict
             and type(prediction.get("logit_q24")) is int
             and type(prediction.get("status")) is str,
             "independent public Q24 prediction is invalid")
        sign = prediction["logit_q24"]
        decision = prediction["status"]
        if decision == "QUANTIZATION_AMBIGUOUS_ABSTAIN":
            if gold:
                pos_abstain += 1
            else:
                neg_abstain += 1
        elif decision == "ACCEPT_POSITIVE_RESEARCH_ONLY":
            need(sign > 0, "accepted positive native Head has invalid sign")
            if gold:
                tp += 1
            else:
                fp += 1
        elif decision == "ACCEPT_NEGATIVE_RESEARCH_ONLY":
            need(sign < 0, "accepted negative native Head has invalid sign")
            if gold:
                fn += 1
            else:
                tn += 1
        else:
            raise Rejected("unregistered native public Q24 Head decision")
    need(tp + fn + pos_abstain == 8
         and tn + fp + neg_abstain == 24,
         "independent original public class totals were not conserved")
    correct = tp + tn
    delivered = tp + tn + fp + fn
    abstentions = pos_abstain + neg_abstain
    need(delivered + abstentions == 32,
         "independent public Q24 heldout task opportunities dropped")
    return {
        "original_heldout_opportunities": 32,
        "actual_accepted_decisions": delivered,
        "abstentions": abstentions,
        "correct_nonabstained": correct,
        "delivered_accuracy_with_abstain_counted_wrong": correct / 32,
        "coverage": delivered / 32,
        "positive_recall_8": tp / 8,
        "negative_specificity_24": tn / 24,
        "balanced_accuracy_with_abstain_counted_wrong":
            (tp / 8 + tn / 24) / 2,
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "positive_abstentions": pos_abstain,
        "negative_abstentions": neg_abstain,
    }


def check_outcome_row(event: dict, *, source: dict, width: int) -> dict:
    need(type(event) is dict and set(event) == {
        "case_id", "source_text_sha256", "logit_q24",
        "head_sign_margin_status", "head_sign_margin_twice_q24_lsb",
        "native_cold_checkpoint_sha256",
    }, "unsealed or foreign public prediction field")
    need(event["case_id"] == source["id"]
         and event["source_text_sha256"] == sha(source["text"].encode("utf-8"))
         and hex_digest(event["native_cold_checkpoint_sha256"]),
         "public native heldout prediction identity/checkpoint SHA changed")
    logit = event["logit_q24"]
    twice_bound = width * 9 + 1
    need(type(logit) is int and -(1 << 63) <= logit < (1 << 63)
         and type(event["head_sign_margin_twice_q24_lsb"]) is int
         and event["head_sign_margin_twice_q24_lsb"] == twice_bound,
         "unbounded or fabricated Q24 Head confidence")
    status = (
        "QUANTIZATION_AMBIGUOUS_ABSTAIN"
        if 2 * abs(logit) <= twice_bound
        else ("ACCEPT_POSITIVE_RESEARCH_ONLY" if logit > 0
              else "ACCEPT_NEGATIVE_RESEARCH_ONLY")
    )
    need(event["head_sign_margin_status"] == status,
         "public native score forged accepted Q24 sign")
    return {"logit_q24": logit, "status": status}


def physical_training_receipt_index(
    source_bytes: bytes, report: dict,
) -> dict[tuple[int, int, str], dict]:
    """Independent 32-model training inventory; CPU time remains descriptive."""
    need(type(source_bytes) is bytes and
         sha(source_bytes) == report.get("training_receipt_sha256"),
         "original physical training receipt SHA mismatch")
    source = unique_json(source_bytes)
    need(type(source) is dict and
         source.get("schema") ==
             "hepta.neuron.real-public-iid-q24-physical-32-arm-train.v1"
         and source.get("authority") == "DENY_ALL"
         and source.get("decision") == "NO_MODEL_PROMOTION"
         and source.get("training_data_kind") ==
             "PUBLIC_Q24_IID_FIT_INPUT_CLAIM_NO_INDEPENDENT_OWNER_SIGNATURE"
         and source.get("physical_models_count") == 32
         and source.get("task_count") == 4
         and source.get("epochs") == 8
         and source.get("optimizer_steps_each") == 32
         and source.get("examples_exposed_per_model") == 512
         and source.get("batch_size") == 16
         and source.get("same_order_batches_per_model") is True
         and source.get("iid_state_reset_per_case") is True
         and source.get("heldout_labels_exposed_to_trainer") is False
         and source.get("original_selected_v1_a0_verified") is False
         and source.get("heldout_or_future_accuracy_evaluated") is False
         and source.get("equal_training_flops_or_memory_verified") is False
         and source.get("ndu_eligible") is False
         and source.get("production_qualification") is False,
         "physical training metadata drift or false production authority")
    records = source.get("models")
    need(type(records) is list and len(records) == 32,
         "incomplete physical training budget/task/arm records")
    seen = {}
    expected = {(task, cap, arm) for task in range(4)
                for cap in BUDGETS for arm in ARMS}
    for row in records:
        need(type(row) is dict, "invalid original physical training model")
        task, cap, arm = (
            row.get("task_id"), row.get("physical_byte_ceiling"), row.get("arm")
        )
        key = (task, cap, arm)
        need(type(task) is int and type(cap) is int and
             key in expected and key not in seen,
             "duplicate/foreign original trained Cell")
        width, params, file_bytes = REGISTERED_BYTE_GEOMETRY[(cap, arm)]
        seconds = row.get("cpu_seconds_self_reported")
        need(type(row.get("hidden_width")) is int and
             row["hidden_width"] == width and
             type(row.get("realized_private_parameters")) is int and
             row["realized_private_parameters"] == params and
             type(row.get("physical_bytes")) is int and
             row["physical_bytes"] == file_bytes and
             row.get("source_weight_file") ==
                 f"{task}/{cap}/{arm}.safetensors" and
             hex_digest(row.get("weight_sha256")) and
             row.get("optimizer_steps") == 32 and
             row.get("examples_exposed") == 512 and
             type(seconds) in (int, float) and
             math.isfinite(seconds) and seconds >= 0.0,
             "trained private Q24 physical shape/optimizer/CPU record changed")
        seen[key] = row
    need(set(seen) == expected, "missing physically trained task/cap/arm slot")
    return seen


def recheck_report(report: dict, original_inputs: dict,
                   observer: dict, heldout_sha256: str,
                   training_receipt_raw: bytes | None = None) -> dict:
    need(type(report) is dict and
         report.get("schema") == "hepta.neuron.real-public-iid-native-q24-heldout.v1"
         and report.get("decision") == "NO_MODEL_SELECTION"
         and report.get("authority") == "DENY_ALL"
         and report.get("original_heldout_cases") == 32
         and report.get("four_binary_tasks") == 4
         and report.get("trained_private_models") == 32
         and report.get("fresh_rust_os_process_invocations") == 2048
         and report.get("unlabeled_prediction_census") == 1024
         and report.get("all_independent_q24_adapter_head_integer_checks") is True
         and report.get("independent_signed_evaluator_custody") is False
         and report.get("original_selected_deployed_v1_no_change_a0_verified") is False
         and report.get("real_future_window_and_negative_transfer_verified") is False
         and report.get("ndu_eligible") is False
         and report.get("production_qualification") is False,
         "incomplete or overclaimed public IID Q24 source report")
    need(hex_digest(report.get("native_rust_binary_sha256"))
         and hex_digest(report.get("training_receipt_sha256"))
         and report.get("heldout_source_sha256") == heldout_sha256
         and report.get("original_public_source_input_id") ==
             original_inputs.get("input_id"),
         "native binary, exact trained source, or original public dataset identity changed")
    need(type(original_inputs) is dict and
         type(original_inputs.get("heldout")) is list
         and len(original_inputs["heldout"]) == 32 and
         type(observer) is dict and
         type(observer.get("rows")) is list and
         len(observer["rows"]) == 32,
         "missing independent original heldout source/label inventory")
    truth = []
    for public, observed in zip(
        original_inputs["heldout"], observer["rows"], strict=True
    ):
        need(type(public) is dict and type(observed) is dict and
             public.get("id") == observed.get("id") and
             type(observed.get("label")) is int and
             0 <= observed["label"] < 4,
             "original registered public label source drift")
        truth.append(observed["label"])
    need([truth.count(i) for i in range(4)] == [8, 8, 8, 8],
         "original selected public task denominators changed")
    physical_index = (
        physical_training_receipt_index(training_receipt_raw, report)
        if training_receipt_raw is not None else None
    )
    records, aggregates = report.get("unlabeled_prediction_records"), report.get("observations")
    need(type(records) is list and type(aggregates) is list and
         len(records) == len(aggregates) == 32,
         "incomplete or duplicated 32-model public-score census")
    expected = {(task, cap, arm) for task in range(4)
                for cap in BUDGETS for arm in ARMS}
    seen = set()
    recomputed = []
    for record, summary in zip(records, aggregates, strict=True):
        need(type(record) is dict and set(record) == {
            "task_id", "arm", "serialized_byte_budget", "hidden_width",
            "physical_model_sha256", "cases",
        } and type(summary) is dict,
             "foreign or missing native output model identity")
        task, budget, arm = (
            record["task_id"], record["serialized_byte_budget"], record["arm"]
        )
        key = (task, budget, arm)
        need(type(task) is int and type(budget) is int and
             key in expected and key not in seen and
             hex_digest(record["physical_model_sha256"]),
             "duplicate or unsupported public model task/capacity/arm")
        seen.add(key)
        width = record["hidden_width"]
        required_width, required_parameters, required_bytes = (
            REGISTERED_BYTE_GEOMETRY[(budget, arm)]
        )
        need(type(width) is int and width == required_width
             and type(summary.get("realized_private_parameters")) is int
             and summary["realized_private_parameters"] == required_parameters
             and type(summary.get("physical_safetensors_file_bytes")) is int
             and summary["physical_safetensors_file_bytes"] == required_bytes,
             "registered physical native Q24 Cell shape/parameters/file bytes drift")
        if physical_index is not None:
            trained = physical_index[key]
            need(record["physical_model_sha256"] == trained["weight_sha256"],
                 "native model digest differs from independently reopened physical trainer")
        need(summary.get("task_id") == task
             and summary.get("serialized_byte_budget") == budget
             and summary.get("arm") == arm
             and summary.get("physical_model_sha256") ==
                 record["physical_model_sha256"]
             and summary.get("heldout_unlabeled_prediction_sha256") ==
                 sha(independent_record_bytes(record))
             and summary.get("independent_native_os_processes") == 64
             and summary.get("independently_checked_original_q24_input_events") == 32,
             "native summary is not bound to original sealed prediction cases")
        cases = record["cases"]
        need(type(cases) is list and len(cases) == 32,
             "missing real heldout case predictions")
        predicted = [
            check_outcome_row(e, source=p, width=width)
            for p, e in zip(original_inputs["heldout"], cases, strict=True)
        ]
        recomputed_binary = independent_binary_metrics(
            [int(y == task) for y in truth], predicted
        )
        for name, value in recomputed_binary.items():
            actual = summary.get(name)
            need(type(actual) is type(value) and actual == value,
                 "independent originally pinned public heldout score changed: " + name)
        for name in (
            "isolated_cold_process_wall_p50_micros",
            "isolated_cold_process_wall_p95_micros",
            "isolated_cold_process_wall_p99_micros",
        ):
            need(type(summary.get(name)) is int and
                 summary[name] > 0,
                 "missing cold native process wall observation")
        need(summary["isolated_cold_process_wall_p50_micros"] <=
             summary["isolated_cold_process_wall_p95_micros"] <=
             summary["isolated_cold_process_wall_p99_micros"],
             "inconsistent descriptive cold-process latency percentile")
        need(summary.get("full_encoder_worker_runtime_or_target_host_slo_verified") is False
             and summary.get("process_wall_includes_binary_startup_model_load_and_json") is True,
             "false production host/worker performance claim")
        recomputed.append({
            "task_id": task, "arm": arm, "serialized_byte_budget": budget,
            "physical_model_sha256": record["physical_model_sha256"],
            "delivered_accuracy": recomputed_binary[
                "delivered_accuracy_with_abstain_counted_wrong"
            ],
            "coverage": recomputed_binary["coverage"],
            "abstentions": recomputed_binary["abstentions"],
            "baseline_is_original_v1": False,
        })
    need(seen == expected, "missing public task/byte-budget/arm combinations")
    control=report.get("static_label_prior_control")
    need(type(control) is dict and
         control.get("correct_cases") == 24 and
         control.get("true_positive_cases") == 8 and
         control.get("true_negative_cases") == 24 and
         control.get("delivered_accuracy") == .75 and
         control.get("balanced_accuracy") == .5 and
         control.get("positive_recall") == 0.0 and
         control.get("not_original_deployed_v1_no_change") is True and
         control.get("not_a_temporal_learning_or_ndu_baseline") is True,
         "fake class-prior control or mistaken deployed V1 baseline")
    return {
        "schema": SCHEMA, "decision": "NO_MODEL_SELECTION",
        "authority": "DENY_ALL",
        "original_public_heldout_cases": 32,
        "distinct_physical_model_count": 32,
        "independently_recomputed_label_free_native_records": 1024,
        "reported_native_processes": 2048,
        "physical_training_receipt_reopened_and_bound":
            physical_index is not None,
        "training_cpu_seconds_are_descriptive_not_whole_system_cost": True,
        "original_public_source_id": original_inputs["input_id"],
        "native_binary_sha256": report["native_rust_binary_sha256"],
        "baseline_original_v1_verified": False,
        "zero_parameter_75pct_control_not_a_v1_model": True,
        "real_future_window_or_negative_transfer_verified": False,
        "independent_evaluator_signature_verified": False,
        "ndu_eligible": False, "production_qualification": False,
        "descriptive_recomputed_scores": recomputed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--heldout", type=Path, required=True)
    parser.add_argument("--training-receipt", type=Path, required=True)
    parser.add_argument("--original-source", type=Path, required=True)
    parser.add_argument("--public-data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        from real_public_iid_q24_inputs import verify_local_original_source, read_original_public_inputs
        original_owner = verify_local_original_source(args.original_source)
        original_inputs = read_original_public_inputs(original_owner, args.public_data)
        import banking77_material
        data = Path(args.public_data)
        _inputs, labels, _selection = banking77_material.prepare(
            read(data / "banking_data/train.csv"),
            read(data / "banking_data/test.csv"),
        )
        heldout_raw = read(args.heldout)
        result = recheck_report(
            unique_json(read(args.score)),
            original_inputs,
            labels,
            sha(heldout_raw),
            training_receipt_raw=read(args.training_receipt),
        )
        with args.output.open("x", encoding="utf-8") as w:
            json.dump(result, w, sort_keys=True, indent=2, allow_nan=False)
            w.write("\n")
        return 0
    except (Rejected, ValueError, OSError, TypeError, KeyError) as e:
        print("BLOCKED_INDEPENDENT_PUBLIC_Q24_SCORE_RECHECK: "+str(e),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
