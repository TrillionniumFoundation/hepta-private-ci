#!/usr/bin/env python3
"""Independently score 32 *real public IID* Q24 trained models with native Rust.

This is a small 64-fit/32-official-heldout BANKING77 descriptive four-class
one-vs-rest canary, NOT chronological/future evidence, NDU or a selected V1
no-change comparator. Models are sealed before this separate evaluator ever
loads heldout observer labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from matched_train import sha_file, unique_json
from near_matched_physical_native_oracle import physically_load, verify
from near_matched_byte_budget import BYTE_CAPS, choose as geometry
from real_public_iid_q24_inputs import (
    CLASSES, read_original_public_inputs, verify_local_original_source,
)
from real_encoder_q24_snapshot_gate import read

ARMS = ("v2", "v3", "ssm", "min_gru")
REPORT_SCHEMA = "hepta.neuron.real-public-iid-native-q24-heldout.v1"


class Refused(ValueError):
    pass


def need(ok: bool, why: str) -> None:
    if not ok:
        raise Refused(why)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def nearest_rank_us(ns: list[int], percentile: int) -> int:
    """Descriptive fresh-process wall p50/p95/p99, NOT worker tick SLO."""
    need(type(ns) is list and len(ns) == 64
         and type(percentile) is int and percentile in (50, 95, 99)
         and all(type(value) is int and value > 0 for value in ns),
         "unbound fresh-native-process wall latency census")
    order = sorted(ns)
    index = (len(order) * percentile + 99) // 100 - 1
    return max(1, (order[index] + 999) // 1000)


def bin_metrics(truth: list[int], raw_outputs: list[dict]) -> dict:
    """All 32 opportunities count, ambiguous abstention never becomes a win."""
    need(type(truth) is list and type(raw_outputs) is list and
         len(truth) == len(raw_outputs) == 32 and
         all(type(x) is int and x in (0, 1) for x in truth),
         "missing 32 binary heldout labels or predictions")
    need(sum(truth) == 8, "unregistered official public positive denominator")
    answers = 0
    correct = 0
    abstain = 0
    positive_hit = 0
    negative_hit = 0
    for label, row in zip(truth, raw_outputs):
        need(type(row) is dict and type(row.get("logit_q24")) is int and
             type(row.get("status")) is str,
             "noninteger or missing original Rust Q24 binary logit")
        result = row["logit_q24"]
        status = row["status"]
        if status == "QUANTIZATION_AMBIGUOUS_ABSTAIN":
            abstain += 1
            continue
        need((result > 0 and status == "ACCEPT_POSITIVE_RESEARCH_ONLY")
             or (result < 0 and status == "ACCEPT_NEGATIVE_RESEARCH_ONLY"),
             "unknown or false accepted quantized Head sign margin")
        answers += 1
        predicted = int(result > 0)
        if predicted == label:
            correct += 1
            if label:
                positive_hit += 1
            else:
                negative_hit += 1
    need(answers + abstain == 32, "dropped real heldout task opportunities")
    return {
        "original_heldout_opportunities": 32,
        "actual_accepted_decisions": answers,
        "abstentions": abstain,
        "correct_nonabstained": correct,
        "delivered_accuracy_with_abstain_counted_wrong": correct / 32,
        "coverage": answers / 32,
        "positive_recall_8": positive_hit / 8,
        "negative_specificity_24": negative_hit / 24,
    }


def independent_head_margin(front: dict, width: int) -> dict:
    """Independent conservative SAME-activation Q24 sign test; no final-use."""
    need(type(front) is dict and type(width) is int and 5 <= width <= 256,
         "missing bound native Head result/width")
    activation = front.get("activation_q24")
    logit = front.get("quantized_head_logit_q24")
    need(type(activation) is list and len(activation) == width
         and all(type(v) is int and abs(v) <= 8 * (1 << 24)
                 for v in activation)
         and type(logit) is int and -(1 << 63) <= logit < (1 << 63),
         "invalid bounded signed-Q24 Head activation/logit")
    # The total worst-case rounding uncertainty for the linear F32->Q24
    # Head on the SAME bounded Q24 activation is (9*width+1)/2 Q24 LSB.
    twice_bound = width * 9 + 1
    status = (
        "QUANTIZATION_AMBIGUOUS_ABSTAIN"
        if 2 * abs(logit) <= twice_bound
        else ("ACCEPT_POSITIVE_RESEARCH_ONLY" if logit > 0
              else "ACCEPT_NEGATIVE_RESEARCH_ONLY")
    )
    need(type(front.get("head_sign_margin_twice_q24_lsb")) is int
         and front["head_sign_margin_twice_q24_lsb"] == twice_bound
         and front.get("head_sign_margin_status") == status,
         "physical Rust Head margin differs from independent Q24 bound")
    return {"logit_q24": logit, "status": status}


def frozen_single_case_trace(row: dict, *, task_id: int) -> dict:
    need(type(task_id) is int and 0 <= task_id < 4,
         "unregistered one-vs-rest public objective")
    need(type(row) is dict and set(row) == {
        "case_id", "source_text_sha256", "feature_q24", "split",
    } and row.get("split") == "heldout",
         "foreign or labeled public heldout row cannot be encoded")
    feat = row["feature_q24"]
    need(type(feat) is list and len(feat) == 32
         and all(type(n) is int and abs(n) <= 8 * (1<<24) for n in feat),
         "wrong real public Q24 feature input dimensions")
    identity = row["case_id"].encode("utf-8")
    return {
        "schema": "hepta.neuron.physical-q24-shadow-trace.v1",
        "scope_digest": digest(b"iid-one-case-scope:" + identity),
        "objective_digest": digest(
            b"no-production-public-one-vs-rest-objective:" + str(task_id).encode()
        ),
        "ndu_digest": digest(b"NO_NDU_IN_PUBLIC_STATIC_EVALUATION"),
        "body_digest": digest(b"frozen-real-public-Q24-text-input:" + identity),
        "events": [{
            "sequence": 1,
            "monotonic_micros": 1,
            "temporal_drive_q24": feat,
            "prediction_q24": [0] * 32,
        }],
    }


def run(args) -> dict:
    # No model training API, no fit/optimizer arguments. The original official
    # heldout targets only enter this separate process AFTER the models exist.
    root = Path(args.models_root)
    need(root.is_dir() and not root.is_symlink(),
         "missing physical completed Q24 research models")
    training_raw = read(root / "training-receipt.json")
    original = unique_json(training_raw)
    need(original.get("schema") ==
             "hepta.neuron.real-public-iid-q24-physical-32-arm-train.v1"
         and original.get("decision") == "NO_MODEL_PROMOTION"
         and original.get("training_data_kind") ==
             "PUBLIC_Q24_IID_FIT_INPUT_CLAIM_NO_INDEPENDENT_OWNER_SIGNATURE"
         and original.get("physical_models_count") == 32
         and original.get("iid_state_reset_per_case") is True
         and original.get("heldout_labels_exposed_to_trainer") is False
         and original.get("original_selected_v1_a0_verified") is False
         and original.get("ndu_eligible") is False
         and original.get("production_qualification") is False,
         "untrusted, mixed, or privileged physical Q24 public-training receipt")
    frozen_plan = unique_json(read(Path(args.plan)))
    held = unique_json(read(Path(args.heldout)))
    need(digest(read(Path(args.plan))) == original["predeclared_plan_sha256"]
         and frozen_plan.get("same_frozen_feature_source") ==
             held.get("input_feature_snapshot_sha256") ==
             original.get("real_public_q24_feature_snapshot_sha256")
         and held.get("schema") ==
             "hepta.neuron.real-public-q24-iid-heldout-unlabeled.v1"
         and held.get("authority") == "DENY_ALL"
         and held.get("holdout_labels_exposed") is False,
         "training model / blind public heldout source identity changed")
    rows = held.get("rows")
    need(type(rows) is list and len(rows) == 32 and
         len({row["case_id"] for row in rows}) == 32,
         "wrong original heldout case census")
    # The original public label owner is loaded after all training. This is
    # software/process separation, NOT cryptographically independent custody.
    original_owner = verify_local_original_source(args.original_source)
    original_inputs = read_original_public_inputs(original_owner, args.public_data)
    need(original_inputs["input_id"] == held.get("source_input_id"),
         "original public source input differs from frozen heldout")
    import banking77_material
    data = Path(args.public_data)
    _, observer, _ = banking77_material.prepare(
        read(data / "banking_data/train.csv"),
        read(data / "banking_data/test.csv"),
    )
    labels = observer["rows"]
    need(type(labels) is list and len(labels) == 32 and
         [row["id"] for row in labels] == [row["case_id"] for row in rows] ==
             [item["id"] for item in original_inputs["heldout"]],
         "published heldout model input drifted from original label custody")
    label_values = [row["label"] for row in labels]
    need(all(type(y) is int and 0 <= y < 4 for y in label_values)
         and [label_values.count(i) for i in range(4)] == [8] * 4,
         "invalid four-class original heldout denominator")
    for actual, source in zip(rows, original_inputs["heldout"]):
        need(actual["source_text_sha256"] ==
             digest(source["text"].encode("utf-8")),
             "heldout source text SHA differs from original public study")
    models = original["models"]
    need(type(models) is list and len(models) == 32 and
         len({(m["task_id"], m["physical_byte_ceiling"], m["arm"]) for m in models}) == 32,
         "missing or duplicate trained Q24 model slot")
    import tempfile
    from pathlib import Path
    binary = Path(args.binary)
    sha_file(binary, args.binary_sha256)
    # Do not upload raw heldout feature vectors or original labels. Trace JSON
    # is a short-lived read-only original single-case Q24 artifact per input.
    metrics = []
    receipts = 0
    with tempfile.TemporaryDirectory() as temp:
        trace_dir = Path(temp)
        traces_by_task = {}
        for task_id in range(4):
            traces = []
            for index, row in enumerate(rows):
                trace = frozen_single_case_trace(row, task_id=task_id)
                raw = canonical(trace)
                path = trace_dir / f"task-{task_id}-case-{index:02d}.json"
                with path.open("xb") as stream:
                    stream.write(raw)
                traces.append((path, digest(raw), trace))
            traces_by_task[task_id] = traces
        for m in models:
            task, cap, arm = (
                m["task_id"], m["physical_byte_ceiling"], m["arm"],
            )
            need(type(task) is int and task in range(4)
                 and type(cap) is int and cap in BYTE_CAPS and arm in ARMS,
                 "foreign Q24 private model/cap/type")
            expected = geometry(arm, cap)
            need(m["hidden_width"] == expected["hidden_width"]
                 and m["rank"] == expected["rank"]
                 and m["physical_bytes"] == expected["physical_safetensors_bytes"]
                 and m["realized_private_parameters"] ==
                     expected["private_parameter_count"]
                 and m["optimizer_steps"] == original["optimizer_steps_each"]
                 and m["examples_exposed"] ==
                     original["examples_exposed_per_model"],
                 "actual model capacity or training exposure mismatched")
            need(m["source_weight_file"] ==
                 f"{task}/{cap}/{arm}.safetensors",
                 "unregistered physical model file path")
            # Reuse independent strict Q24 safetensors inventory/shape/byte
            # oracle with the task-specific model root, never a fake cap label.
            path = root / m["source_weight_file"]
            check_row = {
                "cap": cap, "arm": arm, "hidden_width": m["hidden_width"],
                "rank": m["rank"],
                "weight_file": f"{cap}/{arm}.safetensors",
                "weight_sha256": m["weight_sha256"],
                "physical_bytes": m["physical_bytes"],
                "complete_realized_parameters": m["realized_private_parameters"],
                "budget_kind": "SERIALIZED_SAFETENSORS_BYTES",
                "physical_byte_ceiling": cap,
            }
            weights = physically_load(root / str(task), check_row)
            found = []
            subprocess_wall_nanos = []
            for trace_file, trace_sha, trace in traces_by_task[task]:
                argv = [
                    str(binary.resolve()), "--arm", arm,
                    "--model", str(path.resolve()),
                    "--model-sha256", m["weight_sha256"],
                    "--trace", str(trace_file),
                    "--trace-sha256", trace_sha,
                    "--cap", str(cap),
                    "--hidden-width", str(m["hidden_width"]),
                    "--budget-kind", "SERIALIZED_SAFETENSORS_BYTES",
                ]
                if m["rank"] is not None:
                    argv += ["--rank", str(m["rank"])]
                native_runs = []
                for _ in range(2):
                    wall_started = time.perf_counter_ns()
                    proc = subprocess.run(
                        argv, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        check=False, timeout=30,
                    )
                    subprocess_wall_nanos.append(
                        max(1, time.perf_counter_ns() - wall_started)
                    )
                    need(proc.returncode == 0 and
                         0 < len(proc.stdout) <= 1_000_000,
                         "actual native Q24 task failed: " +
                            proc.stderr[:1200].decode(errors="replace"))
                    native_runs.append(unique_json(proc.stdout))
                need(native_runs[0] == native_runs[1],
                     "same heldout feature, two native OS processes diverged")
                # Independent Rust-vs-Python integer Adapter and Head parity,
                # cold replay and exact physically frozen model+trace SHA.
                check = verify(native_runs[0], trace, check_row, weights, trace_sha)
                need(check["independent_integer_adapter_head_parity"] is True
                     and check["verified_native_adapter_head_event_count"] == 1,
                     "independent real-public Q24 numeric parity failed")
                front = native_runs[0]["frontier"][0]
                found.append(independent_head_margin(front, m["hidden_width"]))
                receipts += 2
            truth = [int(y == task) for y in label_values]
            summary = bin_metrics(truth, found)
            summary.update({
                "isolated_cold_process_wall_p50_micros":
                    nearest_rank_us(subprocess_wall_nanos, 50),
                "isolated_cold_process_wall_p95_micros":
                    nearest_rank_us(subprocess_wall_nanos, 95),
                "isolated_cold_process_wall_p99_micros":
                    nearest_rank_us(subprocess_wall_nanos, 99),
                "process_wall_includes_binary_startup_model_load_and_json": True,
                "full_encoder_worker_runtime_or_target_host_slo_verified": False,
                "task_id": task, "positive_intent": CLASSES[task],
                "arm": arm, "serialized_byte_budget": cap,
                "physical_model_sha256": m["weight_sha256"],
                "realized_private_parameters": m["realized_private_parameters"],
                "physical_safetensors_file_bytes": m["physical_bytes"],
                "independent_native_os_processes": 64,
                "independently_checked_original_q24_input_events": 32,
            })
            metrics.append(summary)
            sha_file(path, m["weight_sha256"])
    need(receipts == 2048 and len(metrics) == 32,
         "incomplete physical 32-model/32-heldout two-process evaluation")
    return {
        "schema": REPORT_SCHEMA,
        "decision": "NO_MODEL_SELECTION", "authority": "DENY_ALL",
        "training_receipt_sha256": digest(training_raw),
        "heldout_source_sha256": digest(read(Path(args.heldout))),
        "original_public_source_input_id": original_inputs["input_id"],
        "real_pretrained_encoder_feature_source_sha256":
            original["real_public_q24_feature_snapshot_sha256"],
        "original_heldout_cases": 32,
        "static_label_prior_control": {
            "name": "ZERO_PARAMETER_ALWAYS_NEGATIVE_ONE_VS_REST",
            "true_negative_cases": 24,
            "true_positive_cases": 8,
            "correct_cases": 24,
            "delivered_accuracy": 0.75,
            "positive_recall": 0.0,
            "not_original_deployed_v1_no_change": True,
            "not_a_temporal_learning_or_ndu_baseline": True,
        },
        "four_binary_tasks": 4, "trained_private_models": 32,
        "fresh_rust_os_process_invocations": receipts,
        "all_independent_q24_adapter_head_integer_checks": True,
        "iid_one_tick_independent_per_case": True,
        "heldout_labels_joined_only_after_training": True,
        "independent_signed_evaluator_custody": False,
        "original_selected_deployed_v1_no_change_a0_verified": False,
        "real_future_window_and_negative_transfer_verified": False,
        "same_model_training_flops_or_runtime_rss_verified": False,
        "ndu_eligible": False, "production_qualification": False,
        "observations": metrics,
    }


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models-root", type=Path, required=True)
    ap.add_argument("--heldout", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--original-source", type=Path, required=True)
    ap.add_argument("--public-data", type=Path, required=True)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--binary-sha256", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args=ap.parse_args()
    try:
        report=run(args)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(report,file,indent=2,sort_keys=True,allow_nan=False)
            file.write("\n")
        return 0
    except (Refused, ValueError, OSError, TypeError, KeyError,
            subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        print("BLOCKED_PUBLIC_IID_NATIVE_HELDOUT: "+str(exc),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
