#!/usr/bin/env python3
"""Physically train 32 research-only Q24-compatible Cells on real public *IID* text features.

4 one-vs-rest BANKING77 tasks x 2 serialized-byte budgets x 4 mechanisms.
The actual pretrained Encoder is NOT executed here: this consumes the
separately frozen/registered physical 32D Q24 feature snapshot.
There is NO signed selected V1, future timestamp, retention, NDU or promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys
import time

from real_encoder_q24_snapshot_gate import read, unique_json
from near_matched_byte_budget import BYTE_CAPS, choose as choose_byte_geometry
from matched_train import make_model

Q = 1 << 24
ARMS = ("v2", "v3", "ssm", "min_gru")
INTENTS = (
    "card_arrival", "cash_withdrawal_not_recognised",
    "exchange_rate", "lost_or_stolen_phone",
)
SCHEMA = "hepta.neuron.real-public-iid-q24-physical-32-arm-train.v1"


class Refused(ValueError):
    pass


def need(ok: bool, reason: str) -> None:
    if not ok:
        raise Refused(reason)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_fit(source: dict, plan: dict) -> tuple[list, str]:
    need(type(source) is dict and
         source.get("schema") == "hepta.neuron.real-public-q24-iid-fit-inputs.v1" and
         source.get("fit_labels_only") is True and
         source.get("holdout_labels_exposed") is False and
         source.get("authority") == "DENY_ALL" and
         source.get("production_qualification") is False and
         source.get("ndu_eligible") is False and
         source.get("feature_dimension") == 32 and
         source.get("temporal_observation_kind") ==
             "UNORDERED_IID_ONE_TICK_PER_CASE_NOT_FUTURE_OR_RETENTION",
         "invalid or promoted original real-public IID fit source")
    need(type(plan) is dict and
         plan.get("schema") ==
             "hepta.neuron.real-public-q24-iid-predeclared-plan.v1" and
         plan.get("authority") == "DENY_ALL" and
         plan.get("decision") == "NO_MODEL_PROMOTION" and
         plan.get("training_execution_performed") is False and
         plan.get("selected_original_v1_no_change_a0_verified") is False and
         plan.get("independent_heldout_labels_joined") is False and
         plan.get("longitudinal_or_future_task_efficacy_claim_permitted") is False and
         plan.get("same_frozen_feature_source") ==
             source.get("input_feature_snapshot_sha256") and
         plan.get("fit_case_count") == 64 and
         plan.get("heldout_case_count") == 32 and
         plan.get("candidate_mechanisms") == list(ARMS) and
         plan.get("candidate_private_serialized_byte_budgets") == list(BYTE_CAPS),
         "predeclared fit-only experiment is not the frozen original")
    need(plan.get("binary_tasks") == [
        {"class_id": i, "positive_intent": name,
         "label_rule": "ONE_VS_REST_FROM_FIT_ONLY"}
        for i, name in enumerate(INTENTS)],
        "label tasks differ from preregistered fixed four intents")
    rows = source.get("rows")
    need(type(rows) is list and len(rows) == 64,
         "exactly 64 real fit cases are required")
    seen = set()
    label_count = [0, 0, 0, 0]
    for row in rows:
        need(type(row) is dict and set(row) == {
            "case_id", "source_text_sha256", "feature_q24", "split", "train_label"
        }, "fit-only Q24 row has unexpected/heldout fields")
        cid, label, feat = row["case_id"], row["train_label"], row["feature_q24"]
        need(type(cid) is str and 0 < len(cid) <= 128 and cid not in seen
             and row["split"] == "fit"
             and type(label) is int and 0 <= label < 4,
             "duplicate, mislabeled or mixed fit source")
        seen.add(cid)
        label_count[label] += 1
        sha = row["source_text_sha256"]
        need(type(sha) is str and len(sha) == 64 and
             all(c in "0123456789abcdef" for c in sha) and
             type(feat) is list and len(feat) == 32 and
             all(type(v) is int and abs(v) <= 8 * Q for v in feat),
             "invalid public Q24 feature/source identity")
    need(label_count == [16, 16, 16, 16], "original frozen four-intent fit denominator drift")
    return rows, source["input_feature_snapshot_sha256"]


def train(args) -> dict:
    need(getattr(args, "research_only", False) is True,
         "real public Q24 research training cannot grant live Cell authority")
    epochs = args.epochs
    seed = args.seed
    need(type(epochs) is int and 1 <= epochs <= 16 and
         type(seed) is int and 0 <= seed < 2**31,
         "invalid bounded public IID training schedule")
    fit_raw = read(Path(args.fit))
    plan_raw = read(Path(args.plan))
    need(digest(fit_raw) == args.fit_sha256 and
         digest(plan_raw) == args.plan_sha256,
         "external physically frozen fit/plan SHA mismatch")
    source, plan = unique_json(fit_raw), unique_json(plan_raw)
    rows, snapshot_sha = validate_fit(source, plan)
    import torch
    from safetensors.torch import save_file, load_file

    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    features = torch.tensor([r["feature_q24"] for r in rows],
                            dtype=torch.float32) / Q
    labels = torch.tensor([r["train_label"] for r in rows], dtype=torch.long)
    need(features.shape == (64, 32) and labels.shape == (64,),
         "real task is not complete 64 fit case grid")
    # Identical 64-case permutations/batches across every candidate and task.
    # Every fit case is exposed exactly once PER epoch, and never as an
    # invented recurrent transition from another public BANKING77 example.
    rng = torch.Generator(device="cpu").manual_seed(seed)
    batches = []
    for epoch in range(epochs):
        indices = torch.randperm(64, generator=rng).tolist()
        batches.extend([indices[i:i+16] for i in range(0, 64, 16)])
    need(len(batches) == 4 * epochs and
         all(len(b) == 16 for b in batches), "unbounded/unmatched true fit exposure")
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    models = []
    for task_id in range(4):
        targets = (labels == task_id).to(torch.float32)
        for cap in BYTE_CAPS:
            for arm in ARMS:
                planned = choose_byte_geometry(arm, cap)
                width, rank = planned["hidden_width"], planned["rank"]
                expected = planned["private_parameter_count"]
                torch.manual_seed(seed)
                adapter = torch.nn.Linear(32, width)
                temporal = make_model(arm, width, rank or 0, torch)
                params = list(adapter.parameters()) + list(temporal.parameters())
                optimizer = torch.optim.AdamW(params, lr=0.03, weight_decay=0.0)
                cpu_start = time.process_time()
                last_loss = None
                for batch in batches:
                    # Independent one-tick Q24 text observations; no fabricated
                    # 'time' or false sample-to-sample temporal memory.
                    x = adapter(features[batch]).clamp(-8.0, 8.0)
                    logits = torch.stack([
                        temporal(x[i:i+1], [0]).reshape(())
                        for i in range(len(batch))
                    ])
                    loss = torch.nn.functional.binary_cross_entropy_with_logits(
                        logits, targets[batch])
                    need(bool(torch.isfinite(loss)), "nonfinite real public task loss")
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(params, 1.0)
                    optimizer.step()
                    with torch.no_grad():
                        for val in adapter.parameters():
                            val.clamp_(-8.0, 8.0)
                        for name, val in temporal.named_parameters():
                            if name.startswith("head."):
                                val.clamp_(-8.0, 8.0)
                            elif (arm == "ssm" and name == "decay_per_step") or (
                                    arm == "v3" and name == "gate_bias"):
                                val.clamp_(0.0, 1.0)
                            else:
                                val.clamp_(-1.0, 1.0)
                    last_loss = float(loss.detach())
                tensors = {
                    "adapter.weight": adapter.weight.detach().cpu().contiguous().float(),
                    "adapter.bias": adapter.bias.detach().cpu().contiguous().float(),
                    "structure.projection": torch.full((width,), Q, dtype=torch.int64),
                }
                for name, val in temporal.named_parameters():
                    tensor = val.detach().cpu().contiguous()
                    if name.startswith("head."):
                        tensors[name] = tensor.float()
                    else:
                        tensors["temporal." + name] = torch.round(tensor * Q).to(torch.int64)
                count = sum(v.numel() for v in tensors.values())
                need(count == expected and
                     all(bool(torch.isfinite(v.float()).all()) for v in tensors.values()),
                     "physical public trained Cell tensor inventory mismatch")
                rel = f"{task_id}/{cap}/{arm}.safetensors"
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                save_file(tensors, str(target))
                reopened = load_file(str(target), device="cpu")
                need(set(reopened) == set(tensors) and all(
                    torch.equal(reopened[k], v) for k, v in tensors.items()),
                    "persisted public Q24 Cell tensors changed on reload")
                raw = target.read_bytes()
                need(len(raw) == planned["physical_safetensors_bytes"] and
                     len(raw) <= cap and
                     (cap - len(raw)) * 100 <= cap * 2,
                     "public trained Cell exceeds physical byte-normalized budget")
                models.append({
                    "task_id": task_id, "arm": arm,
                    "physical_byte_ceiling": cap, "hidden_width": width,
                    "rank": rank, "source_weight_file": rel,
                    "weight_sha256": digest(raw),
                    "physical_bytes": len(raw),
                    "realized_private_parameters": count,
                    "optimizer_steps": 4 * epochs,
                    "examples_exposed": 64 * epochs,
                    "train_last_loss": last_loss,
                    "cpu_seconds_self_reported": round(time.process_time() - cpu_start, 6),
                })
    need(len(models) == 32 and
         len({m["weight_sha256"] for m in models}) == 32,
         "training produced collapsed or incomplete physical public models")
    result = {
        "schema": SCHEMA,
        "authority": "DENY_ALL", "decision": "NO_MODEL_PROMOTION",
        "train_source_sha256": digest(fit_raw),
        "predeclared_plan_sha256": digest(plan_raw),
        "real_public_q24_feature_snapshot_sha256": snapshot_sha,
        "training_data_kind": "GENUINE_BANKING77_PUBLIC_IID_NOT_FUTURE",
        "task_count": 4, "physical_models_count": 32,
        "epochs": epochs, "optimizer_steps_each": 4 * epochs,
        "examples_exposed_per_model": 64 * epochs,
        "batch_size": 16,
        "same_order_batches_per_model": True,
        "iid_state_reset_per_case": True,
        "actual_model_tensor_files_created_and_reopened": True,
        "actual_pretrained_encoder_invoked_in_trainer": False,
        "original_selected_v1_a0_verified": False,
        "heldout_labels_exposed_to_trainer": False,
        "heldout_or_future_accuracy_evaluated": False,
        "equal_training_flops_or_memory_verified": False,
        "ndu_eligible": False, "production_qualification": False,
        "models": models,
    }
    with (root / "training-receipt.json").open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--fit-sha256", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--research-only", action="store_true")
    args = parser.parse_args()
    try:
        train(args)
        return 0
    except (Refused, ValueError, OSError, KeyError, TypeError) as exc:
        print("BLOCKED_REAL_PUBLIC_Q24_TRAIN: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
