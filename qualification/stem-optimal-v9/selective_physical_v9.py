"""Physically encode only the selected 8 heldout inputs, never all 32.

Research only. Existing original 64 FIT inputs still require a real encoder pass.
All model/head/candidate identities bind the immutable V3/V5/V8 originals.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
for name in ("stem-optimal-v1", "stem-optimal-v5", "stem-optimal-v8"):
    sys.path.insert(0, str(ROOT / name))
import stem_candidate_v1 as old
import paired_review_v5 as custody
import selective_route_v8 as route

SCHEMA = "hepta.stem.selective.physical.v9"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def validate_plan(source, cheap, plan, materials, model):
    require(model in route.CANDIDATES and source["source_plan_sha256"] == route.SOURCE_SHA,
            "wrong source/model")
    old.verify_prepared  # Explicitly do not reinterpret V3 as V1.
    require(plan["schema"] == route.SCHEMA and
            plan["source_plan_sha256"] == route.SOURCE_SHA and
            plan["selected_case_ids"] == route.select_unlabelled(
                route._scores(cheap, source["heldout"], route.CHEAP_ARM, cheap=True)),
            "unsealed or label-informed route")
    require(plan["evidence"]["actual_new_encoder_sequence_forwards"] == 0 and
            plan["evidence"]["measured_heldout_encoder_savings"] is False and
            plan["authority"] == "DENY_ALL" and plan["production_authorized"] is False,
            "counterfactual cannot confer authority")
    require(materials["training"] == {"seed": 17, "steps": 100,
            "learning_rate": 0.006, "per_cell_parameters": 6914, "cells": 4},
            "unmatched frozen head training")
    fit_ids = {r["case_id"] for r in source["train"]}
    test = {r["case_id"]: r for r in source["heldout"]}
    selected = plan["selected_case_ids"]
    require(len(fit_ids) == 64 and len(test) == 32 and len(selected) == 8 and
            len(set(selected)) == 8 and set(selected).issubset(test) and
            not fit_ids.intersection(test), "source/selection fanout contamination")
    return [test[c] for c in selected]


def physical_selected(source, cheap, plan, materials, original, model):
    selected = validate_plan(source, cheap, plan, materials, model)
    require(original["candidate"] == model and
            original["schema"] == "hepta.stem.charge-stress.physical-unattested.v3" and
            original["source_plan_sha256"] == route.SOURCE_SHA and
            original["actual_weight_sha256"] == materials["candidates"][model]["weight_sha256"] and
            original["material_manifest_sha256"] == old.sha256(old.canonical(materials)) and
            original["authority"] == "DENY_ALL" and original["production_authorized"] is False,
            "unmatched original model material")
    import torch
    torch.set_num_threads(2)
    wall, cpu = time.perf_counter(), time.process_time()
    tokenizer, backbone = old._material_model(materials["candidates"][model])
    load_seconds = time.perf_counter() - wall
    features_start = time.perf_counter()
    fit_features, fit_batches = old._encode([r["text"] for r in source["train"]],
                                             tokenizer, backbone)
    selected_features, selected_batches = old._encode(
        [r["text"] for r in selected], tokenizer, backbone)
    encoding_seconds = time.perf_counter() - features_start
    require(tuple(fit_features.shape) == (64, 384) and
            tuple(selected_features.shape) == (8, 384) and
            fit_batches == 4 and selected_batches == 1,
            "unexpected real encoder physical shape/forward census")
    heads = old._torch_head_training(fit_features,
                                    [r["label"] for r in source["train"]],
                                    selected_features, config=materials["training"])
    require(heads["initial_head_sha256"] == original["initial_head_sha256"] and
            heads["trained_head_sha256"] == original["trained_head_sha256"],
            "same pretrained Head must be exactly reproducible")
    original_by_id = {r["case_id"]: r for r in original["rows"]}
    rows = []
    maximum_deviation = 0.0
    for i, case in enumerate(selected):
        baseline = original_by_id[case["case_id"]]["scores"]
        observed = {arm: heads[arm][i] for arm in ("learned", "centroid", "frozen_init")}
        for arm in observed:
            for a, b in zip(observed[arm], baseline[arm]):
                require(math.isfinite(a) and math.isfinite(b), "nonfinite original prediction")
                maximum_deviation = max(maximum_deviation, abs(a - b))
        rows.append({"case_id": case["case_id"], "source_sha256": case["source_sha256"],
                     "selected_scores": observed})
    # Physical equivalence is an empirical acceptance gate, never silently
    # reinterpret slightly different logits as historical case predictions.
    require(maximum_deviation <= 5e-4, "original real-forward parity drift")
    return {
        "schema": SCHEMA, "candidate": model,
        "source_plan_sha256": route.SOURCE_SHA,
        "model_revision": materials["candidates"][model]["revision"],
        "actual_weight_sha256": materials["candidates"][model]["weight_sha256"],
        "original_trained_head_sha256": original["trained_head_sha256"],
        "selected_case_ids": plan["selected_case_ids"], "rows": rows,
        "max_abs_original_probability_drift": maximum_deviation,
        "physical_encoder_train_sequences": 64,
        "physical_encoder_test_sequences": 8,
        "physical_encoder_batches": fit_batches + selected_batches,
        "new_total_encoder_sequences": 72,
        "original_v3_total_encoder_sequences": 96,
        "observed_test_sequence_count_reduction": 24,
        "actual_model_load_wall_seconds": load_seconds,
        "actual_feature_encode_wall_seconds": encoding_seconds,
        "actual_total_wall_seconds": time.perf_counter() - wall,
        "actual_total_cpu_seconds": time.process_time() - cpu,
        "self_reported_process_maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "energy_joules": None, "p99_latency_ms": None,
        "independent_future_windows": 0, "matched_host_lifecycle_savings_verified": False,
        "new_source_family": False, "stem_winner_verified": False,
        "production_authorized": False, "cell_split_authorized": False,
        "disposition": "HOLD_NO_GO", "authority": "DENY_ALL",
    }


def main():
    p = argparse.ArgumentParser()
    for n in ("manifest", "zip-dir", "plan", "materials", "candidate", "output"):
        p.add_argument("--" + n, required=True)
    a = p.parse_args()
    lock = json.loads(Path(a.manifest).read_text())
    root = Path(a.zip_dir)
    parts = {n: custody.locked_json(root / (n + ".zip"), lock["artifacts"], n)
             for n in ("source_v3", "source_v4", "cheap_v4", a.candidate)}
    require(parts["source_v3"] == parts["source_v4"], "original publisher source mismatch")
    plan = json.loads(Path(a.plan).read_text())
    # The route must be regenerated from exact archived original predictions,
    # never accepted as a caller-selected list alone.
    original_runs = {n: custody.locked_json(root/(n+".zip"), lock["artifacts"], n)
                     for n in route.CANDIDATES}
    derived = route.produce(parts["source_v3"], parts["source_v4"],
                            original_runs, parts["cheap_v4"])
    require(plan == derived, "untrusted or stale selective plan")
    report = physical_selected(parts["source_v3"], parts["cheap_v4"], plan,
                               old.load_materials(Path(a.materials)),
                               parts[a.candidate], a.candidate)
    path = Path(a.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(old.canonical(report) + b"\n")
        stream.flush()
    print(json.dumps({"digest": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "candidate": a.candidate, "test_encoder_sequences": 8,
                      "disposition": "HOLD_NO_GO", "authority": "DENY_ALL"},sort_keys=True))


if __name__ == "__main__":
    main()
