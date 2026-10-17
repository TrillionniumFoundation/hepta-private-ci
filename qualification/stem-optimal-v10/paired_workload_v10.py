"""Paired measured full-vs-sparse CPU inference with one genuinely loaded Stem.

Research only: all 64 FIT encodes, all bench warmups, and BOTH measured arms
are physically paid, not savings. Refuse original Head/score drift and authority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import resource
import statistics
import sys
import time

SCHEMA = "hepta.stem.original-physical-paired.v10"
CANDIDATES = ("granite47", "granite97", "mmbert140")
ARM_ORDER = (("selected", "full"), ("full", "selected"),
             ("selected", "full"), ("full", "selected"))
SELECTED = 8
TOTAL = 32
TRAIN = 64
TOLERANCE = 5e-4


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode()


def checksum(state):
    h = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        h.update(name.encode("ascii") + b"\x00")
        h.update(tensor.contiguous().detach().cpu().numpy().tobytes())
    return h.hexdigest()


def make_head_and_fit(features, labels, *, config):
    """Exact historical V3 Head operations, with checkpoint parity proof."""
    import torch
    import torch.nn.functional as F

    require(config == {"seed": 17, "steps": 100, "learning_rate": 0.006,
                       "per_cell_parameters": 6914, "cells": 4},
            "not the original Head training budget")
    require(tuple(features.shape) == (TRAIN, 384) and
            len(labels) == TRAIN and all(type(i) is int and 0 <= i < 4 for i in labels),
            "untrusted training feature/label shape")
    torch.manual_seed(config["seed"])
    torch.use_deterministic_algorithms(True)

    class CellHeads(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.a = torch.nn.Parameter(torch.randn((4, 8, 384)) * 0.01)
            self.b = torch.nn.Parameter(torch.zeros((4, 384, 8)))
            self.gate = torch.nn.Parameter(torch.zeros((4, 384)))
            self.gate_bias = torch.nn.Parameter(torch.zeros((4,)))
            self.out = torch.nn.Parameter(torch.randn((4, 384)) * 0.01)
            self.out_bias = torch.nn.Parameter(torch.zeros((4,)))

        def forward(self, x):
            bottleneck = torch.einsum("bd,crd->bcr", x, self.a)
            residual = torch.einsum("bcr,cdr->bcd", bottleneck, self.b)
            gate = torch.sigmoid(torch.einsum("bd,cd->bc", x, self.gate) + self.gate_bias)
            y = x.unsqueeze(1) + gate.unsqueeze(-1) * residual / 8.0
            return (y * self.out.unsqueeze(0)).sum(-1) + self.out_bias

    head = CellHeads()
    require(sum(t.numel() for t in head.parameters()) == 27656, "Head scalar drift")
    initial = checksum(copy.deepcopy(head.state_dict()))
    optimizer = torch.optim.Adam(head.parameters(), lr=config["learning_rate"])
    label_tensor = torch.tensor(labels, dtype=torch.long)
    started = time.perf_counter()
    for _ in range(config["steps"]):
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(head(features), label_tensor)
        require(bool(torch.isfinite(loss).item()), "nonfinite fitted Head")
        loss.backward()
        optimizer.step()
    elapsed = time.perf_counter() - started
    learned = checksum(head.state_dict())
    require(learned != initial, "no fitted Head update")
    head.eval()
    return head, {"initial_sha256": initial, "trained_sha256": learned,
                  "train_wall_seconds": elapsed, "actual_optimizer_updates": config["steps"]}


def validate_original_route(source, cheap, original, plan, candidate):
    import importlib
    # Retained immutable source code owns original source, no-gold and route gates.
    base = Path(__file__).resolve().parents[1]
    for d in ("stem-optimal-v1", "stem-optimal-v5", "stem-optimal-v8"):
        sys.path.insert(0, str(base / d))
    v8 = importlib.import_module("selective_route_v8")
    v5 = importlib.import_module("paired_review_v5")
    require(candidate in CANDIDATES and plan["schema"] == v8.SCHEMA and
            source["source_plan_sha256"] == v8.SOURCE_SHA and
            original["candidate"] == candidate and original["source_plan_sha256"] == v8.SOURCE_SHA and
            plan["authority"] == original["authority"] == "DENY_ALL" and
            plan["production_authorized"] is False and original["production_authorized"] is False,
            "not frozen original model or no-effect route")
    cheap_probs = v8._scores(cheap, source["heldout"], v8.CHEAP_ARM, cheap=True)
    expected = v8.select_unlabelled(cheap_probs)
    require(plan["selected_case_ids"] == expected and len(expected) == SELECTED,
            "prelabel frozen route changed")
    expected_rows = {r["case_id"]: r for r in source["heldout"]}
    require(len(expected_rows) == TOTAL and len(source["train"]) == TRAIN and
            all("label" not in row for row in source["heldout"]),
            "heldout label in producer")
    require(v5.SOURCE_PLAN_SHA == source["source_plan_sha256"], "wrong source identity")
    require(len(original["rows"]) == TOTAL and
            {r["case_id"] for r in original["rows"]} == set(expected_rows),
            "original model case roster drift")
    return [expected_rows[k] for k in expected]


def paired_runs(model, tokenizer, head, fit_source, heldout, selected, *, n_rounds=4):
    """Actually pay and meter both strategies in the SAME resident model.

    No negative temperature or end-to-end production claim from this contract.
    """
    import torch
    import torch.nn.functional as F
    require(n_rounds == 4 and len(heldout) == TOTAL and len(selected) == SELECTED
            and len(set(r["case_id"] for r in heldout)) == TOTAL
            and len(set(r["case_id"] for r in selected)) == SELECTED
            and set(r["case_id"] for r in selected).issubset(
                {r["case_id"] for r in heldout}), "wrong fixed paired input set")
    # Original owner has a fixed batch-size-16 encoder call and counts real batches.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stem-optimal-v1"))
    import stem_candidate_v1 as old
    arms = {"selected": selected, "full": heldout}
    outputs = {"selected": [], "full": []}
    timings = {"selected": [], "full": []}
    actually_paid = {"selected": 0, "full": 0}
    actual_batches = {"selected": 0, "full": 0}
    for order in ARM_ORDER:
        for arm in order:
            rows = arms[arm]
            start_wall, start_cpu = time.perf_counter(), time.process_time()
            matrix, batch_count = old._encode([r["text"] for r in rows], tokenizer, model)
            with torch.inference_mode():
                logits = head(matrix)
                scores = F.softmax(logits, dim=-1).detach().cpu().tolist()
            wall = time.perf_counter() - start_wall
            cpu = time.process_time() - start_cpu
            require(tuple(matrix.shape) == (len(rows), 384) and
                    len(scores) == len(rows) and
                    batch_count == (1 if arm == "selected" else 2),
                    "actual Encoder forward census not observed")
            for score in scores:
                require(len(score) == 4 and all(math.isfinite(x) and 0 <= x <= 1 for x in score)
                        and abs(sum(score) - 1) < 1e-5, "nonfinite model scores")
            actually_paid[arm] += len(rows)
            actual_batches[arm] += batch_count
            outputs[arm].append({r["case_id"]: scores[i] for i, r in enumerate(rows)})
            timings[arm].append({"wall_seconds": wall, "cpu_seconds": cpu,
                                 "actual_sequences": len(rows), "batches": batch_count})
    return timings, outputs, actually_paid, actual_batches


def observed_parity(outputs, original, selected):
    original_by_id = {r["case_id"]: r["scores"]["learned"] for r in original["rows"]}
    require(len(original_by_id) == TOTAL, "unpaired original model receipt")
    selected_ids = {r["case_id"] for r in selected}
    max_original_drift = 0.0
    max_paired_drift = 0.0
    for full, sparse in zip(outputs["full"], outputs["selected"]):
        require(len(full) == TOTAL and set(sparse) == selected_ids,
                "not same original paired input roster")
        for cid, actual in full.items():
            baseline = original_by_id[cid]
            for a, b in zip(actual, baseline):
                max_original_drift = max(max_original_drift, abs(a - b))
            if cid in selected_ids:
                for a, b in zip(actual, sparse[cid]):
                    max_paired_drift = max(max_paired_drift, abs(a - b))
    require(max_original_drift <= TOLERANCE and max_paired_drift <= TOLERANCE,
            "same original model/head numerical parity failed")
    return {"max_original_v3_probability_abs_drift": max_original_drift,
            "max_full_vs_selected_probability_abs_drift": max_paired_drift}


def run_physical(source, cheap, plan, originals, materials, candidate):
    import torch
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stem-optimal-v1"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stem-optimal-v4"))
    import stem_candidate_v1 as old
    import cheap_lexical_stem_v4 as lexical

    original = originals[candidate]
    selected = validate_original_route(source, cheap, original, plan, candidate)
    require(materials["candidates"][candidate]["weight_sha256"] ==
            original["actual_weight_sha256"] and
            old.sha256(old.canonical(materials)) == original["material_manifest_sha256"],
            "untrusted original pretrained weights")
    torch.set_num_threads(2)
    total_wall, total_cpu = time.perf_counter(), time.process_time()
    # This route is real local CPU work and cannot be imported from another run's meter.
    cheap_result = lexical.compute(source)
    require(cheap_result["source_plan_sha256"] == cheap["source_plan_sha256"] and
            cheap_result["training_rows"] == TRAIN and cheap_result["prediction_rows"] == TOTAL,
            "original cheap control identity mismatch")
    saved = {r["case_id"]: r["scores"] for r in cheap["rows"]}
    for row in cheap_result["rows"]:
        require(row["case_id"] in saved and all(
            abs(a-b) < 1e-11 for arm in lexical.ARMS
            for a,b in zip(row["scores"][arm],saved[row["case_id"]][arm])),
            "original cheap prediction numerical mismatch")
    cheap_cost = cheap_result["cost"]
    load_start = time.perf_counter()
    tokenizer, backbone = old._material_model(materials["candidates"][candidate])
    load_elapsed = time.perf_counter()-load_start
    fit_start = time.perf_counter()
    fit_features, fit_batches = old._encode([r["text"] for r in source["train"]],
                                           tokenizer, backbone)
    fit_elapsed = time.perf_counter()-fit_start
    require(tuple(fit_features.shape) == (TRAIN,384) and fit_batches == 4,
            "original fit-model forward census")
    head, checkpoints = make_head_and_fit(fit_features,
                                          [r["label"] for r in source["train"]],
                                          config=materials["training"])
    require(checkpoints["initial_sha256"] == original["initial_head_sha256"] and
            checkpoints["trained_sha256"] == original["trained_head_sha256"],
            "same source/head training does not reproduce original checkpoint")
    timings, outputs, paid, batch_counts = paired_runs(
        backbone, tokenizer, head, source["train"], source["heldout"], selected)
    parity = observed_parity(outputs, original, selected)
    def median(arm,key):
        return statistics.median(t[key] for t in timings[arm])
    return {
        "schema": SCHEMA, "candidate": candidate,
        "source_plan_sha256": source["source_plan_sha256"],
        "original_trained_head_sha256": original["trained_head_sha256"],
        "actual_weight_sha256": original["actual_weight_sha256"],
        "original_v3_model_revision": original["model_revision"],
        "recorded_v3_correctness_not_rejudged": True,
        "cheap_actual_wall_seconds": cheap_cost["elapsed_wall_seconds"],
        "cheap_actual_cpu_seconds": cheap_cost["elapsed_cpu_seconds"],
        "model_load_wall_seconds": load_elapsed,
        "fit_encode_wall_seconds": fit_elapsed,
        "fit_training_wall_seconds": checkpoints["train_wall_seconds"],
        "fit_training_actual_updates": checkpoints["actual_optimizer_updates"],
        "fit_physical_encoder_sequences": TRAIN,
        "fit_physical_encoder_batches": fit_batches,
        "counterbalanced_order": [list(x) for x in ARM_ORDER],
        "measured_arm_timings": timings,
        "measured_arm_sequence_counts": paid,
        "measured_arm_batch_counts": batch_counts,
        "per_arm_median_query_wall_seconds": {
            arm: median(arm,"wall_seconds") for arm in ("selected", "full")},
        "per_arm_median_query_cpu_seconds": {
            arm: median(arm,"cpu_seconds") for arm in ("selected", "full")},
        "measured_full_and_selected_both_executed": True,
        "actual_total_workload_encoder_sequences": TRAIN+paid["selected"]+paid["full"],
        "actual_total_workload_encoder_batches": fit_batches+batch_counts["selected"]+batch_counts["full"],
        "paid_workload_total_wall_seconds": time.perf_counter()-total_wall,
        "paid_workload_total_cpu_seconds": time.process_time()-total_cpu,
        "self_reported_same_process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss *1024,
        **parity,
        "source_independent_families":1,"future_windows":0,
        "physical_inference_arms_executed":True,
        "amortized_full_lifecycle_savings_verified":False,
        "production_p99_gpu_energy_wal_attested":False,
        "negative_transfer_verified":False,"ndu_net_gain_verified":False,
        "stem_winner_verified":False,"production_authorized":False,
        "cell_split_authorized":False,"authority":"DENY_ALL","disposition":"HOLD_NO_GO",
    }


def main():
    p = argparse.ArgumentParser()
    for key in ("manifest", "zip-dir", "materials", "candidate", "output"):
        p.add_argument("--"+key,required=True)
    args = p.parse_args()
    base=Path(__file__).resolve().parents[1]
    for d in ("stem-optimal-v5", "stem-optimal-v8"):
        sys.path.insert(0,str(base/d))
    import paired_review_v5 as v5
    import selective_route_v8 as v8
    lock=json.loads(Path(args.manifest).read_text())
    require(lock["schema"]=="hepta.stem.original-hard-charge.lock.v5" and
            lock["authority"]=="DENY_ALL","untrusted archive lock")
    folder=Path(args.zip_dir)
    docs={role:v5.locked_json(folder/(role+".zip"),lock["artifacts"],role) for role in v5.ROLES}
    require(docs["source_v3"]==docs["source_v4"],"unaligned source cohorts")
    originals={n:docs[n] for n in CANDIDATES}
    plan=v8.produce(docs["source_v3"],docs["source_v4"], originals,docs["cheap_v4"])
    sys.path.insert(0,str(base/"stem-optimal-v1"))
    import stem_candidate_v1 as old
    material=old.load_materials(Path(args.materials))
    result=run_physical(docs["source_v3"],docs["cheap_v4"],plan,originals,material,args.candidate)
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("xb") as out:
        out.write(canonical(result)+b"\n")
        out.flush()
    print(json.dumps({"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
        "candidate":args.candidate,"physical_full_and_selected":True,
        "authority":"DENY_ALL","disposition":"HOLD_NO_GO"},sort_keys=True))

if __name__=="__main__":
    main()
