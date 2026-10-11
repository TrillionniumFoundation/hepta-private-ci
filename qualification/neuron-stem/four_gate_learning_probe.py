#!/usr/bin/env python3
"""Executed controlled CPU learning/reasoning/control experiments.

Generated vector and graph tasks only; no genuine Hepta observations, downloaded
pretrained model, trusted future clock, or production authority. The graph model
has explicit message-passing inductive bias; its scores do not prove open-domain
reasoning. All actual losses, regressions and failed comparisons are retained.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import hashlib
import math
import os
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from four_gate_core import (NDU_ARMS, TASKS, PredictionJournal, canonical, causal_depth,
                            digest, generic_nested_risk, latency, metrics, read_jsonl,
                            recursive_value, require, risk_ce, verify_journal, write_jsonl_once,
                            write_once)
from four_gate_compute_probe import weights_digest

SEED = 20261011


def configure(seed=SEED):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    np.random.seed(seed % 2**32)


def measured_work(key, phase, start):
    return {"physical_work_id": key, "phase": phase,
            "wall_seconds": time.perf_counter() - start[0], "cpu_seconds": time.process_time() - start[1]}


def clock():
    return time.perf_counter(), time.process_time()


class GatedHead(nn.Module):
    def __init__(self, width=24):
        super().__init__()
        self.gate, self.drive, self.readout = nn.Linear(width, 16), nn.Linear(width, 16), nn.Linear(16, 2)

    def forward(self, x):
        return self.readout(torch.sigmoid(self.gate(x)) * F.silu(self.drive(x)))


def fit(model, x, y, steps, lr=.02):
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    model.train()
    last = None
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(model(x), y)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.)
        optimizer.step()
        last = float(loss.detach())
    model.eval()
    return last


def probability(model, features):
    with torch.no_grad():
        return model(features).softmax(-1).tolist()


def cell_probe(root, few_shot, *, cells=12, events_per_cell=128):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    configure(SEED + few_shot)
    protocol = {"kind": "controlled_vector_cell_learning", "seed": SEED + few_shot,
                "cells": cells, "few_shot": few_shot, "events_per_cell": events_per_cell,
                "historical_fit_steps": 40, "online_steps_per_event": 1, "retention_brier_cap": .02,
                "ood_calibration_quantile": .10, "independent_calendar_windows": False,
                "production_promotion_permitted": False}
    write_once(root / "protocol.json", protocol)
    time0 = clock()
    stem = nn.Sequential(nn.Linear(8, 24), nn.Tanh()).eval()
    for parameter in stem.parameters():
        parameter.requires_grad_(False)
    stem_sha = weights_digest(stem)
    truth = torch.randn(cells, 8)
    truth[:, 0] += 2.  # Shared component plus genuinely different per-Cell tasks.
    generators = [torch.Generator().manual_seed(SEED + 10000 * i + few_shot) for i in range(cells)]
    def sample(i, count, ood=False):
        x = torch.randn(count, 8, generator=generators[i])
        if ood:
            x = 3 * x + 2
        y = (x @ truth[i] > 0).long()
        return x, y
    historical = [sample(i, few_shot) for i in range(cells)]
    retained = [sample(i, 96) for i in range(cells)]
    calibration = [sample(i, 64) for i in range(cells)]
    nochange = GatedHead()
    fit(nochange, stem(torch.cat([x for x, _ in historical])), torch.cat([y for _, y in historical]), 40)
    nochange_sha = weights_digest(nochange)
    frozen, learned, optimizers = [], [], []
    for x, y in historical:
        model = copy.deepcopy(nochange)
        fit(model, stem(x), y, 40)
        frozen.append(model)
        learned.append(copy.deepcopy(model))
        optimizers.append(torch.optim.AdamW(learned[-1].parameters(), lr=.008))
    initial = [weights_digest(m) for m in frozen]
    setup_work = measured_work(f"cell-{few_shot}/historical-training", "training", time0)
    before = [metrics(probability(learned[i], stem(x)), y.tolist()) for i, (x, y) in enumerate(retained)]
    thresholds = {}
    for arm in ("no_change", "same_init_frozen", "learned"):
        conf = []
        for i, (x, _) in enumerate(calibration):
            model = nochange if arm == "no_change" else frozen[i]
            conf.extend(max(p) for p in probability(model, stem(x)))
        thresholds[arm] = float(np.quantile(conf, .10))
    records, outcomes, preds, labels = [], [], {k: [] for k in thresholds}, []
    chain = initial.copy()
    train_seconds = 0.
    trial0 = clock()
    with PredictionJournal(root / "prelabel.jsonl") as journal:
        for step in range(events_per_cell):
            for i in range(cells):
                x, hidden_label = sample(i, 1)
                features = stem(x)
                key = f"fewshot-{few_shot}/cell-{i}/event-{step}"
                p = {"no_change": probability(nochange, features)[0],
                     "same_init_frozen": probability(frozen[i], features)[0],
                     "learned": probability(learned[i], features)[0]}
                pre = weights_digest(learned[i])
                require(pre == chain[i] and weights_digest(frozen[i]) == initial[i], "Head lineage/frozen weights drift")
                if step == 0:
                    require(p["learned"] == p["same_init_frozen"], "initial control mismatch")
                prediction = {"case_id": key, "cell_id": i, "synthetic_arrival_index": len(records),
                              "stem_digest": stem_sha, "preupdate_head_digest": pre,
                              "frozen_head_digest": initial[i], "probabilities": p,
                              "input_digest": digest(x.tolist())}
                seal = journal.seal(prediction)
                journal.before_label_reveal(key, seal)
                y = int(hidden_label.item())
                outcomes.append({"case_id": key, "label": y, "prediction_seal": seal,
                                 "observer": "local_generated_linear_oracle_not_independent_hepta_owner"})
                labels.append(y)
                for arm in preds:
                    preds[arm].append(p[arm])
                t = time.perf_counter()
                optimizers[i].zero_grad(set_to_none=True)
                loss = F.cross_entropy(learned[i](features), hidden_label)
                loss.backward()
                nn.utils.clip_grad_norm_(learned[i].parameters(), 1.)
                optimizers[i].step()
                train_seconds += time.perf_counter() - t
                chain[i] = weights_digest(learned[i])
                records.append({"case_id": key, "prediction_seal": seal, "preupdate_head_digest": pre,
                                "postupdate_head_digest": chain[i], "optimizer_steps": 1,
                                "local_update_loss": float(loss.detach())})
    trial_work = measured_work(f"cell-{few_shot}/test-then-learn", "evaluation", trial0)
    after = [metrics(probability(learned[i], stem(x)), y.tolist()) for i, (x, y) in enumerate(retained)]
    ood = {arm: [] for arm in preds}
    for i in range(cells):
        x, _ = sample(i, 96, ood=True)
        for arm in ood:
            model = nochange if arm == "no_change" else frozen[i] if arm == "same_init_frozen" else learned[i]
            ood[arm].extend(max(p) >= thresholds[arm] for p in probability(model, stem(x)))
    require(weights_digest(stem) == stem_sha and weights_digest(nochange) == nochange_sha, "shared Stem/no-change weights changed")
    require([weights_digest(m) for m in frozen] == initial, "frozen control changed")
    verified_count = verify_journal(read_jsonl(root / "prelabel.jsonl"))
    summary = {"schema": "hepta.controlled-cell-probe.v1", "protocol": protocol,
               "prelabel_records_checked": verified_count, "all_observed_optimizer_steps": len(records),
               "stem_frozen": True, "same_init_frozen_heads_unchanged": True,
               "no_change_weights_unchanged": True, "per_head_parameters": sum(p.numel() for p in learned[0].parameters()),
               "initial_head_digests": initial, "final_head_digests": chain,
               "metrics": {arm: metrics(preds[arm], labels) for arm in preds},
               "retention_before": before, "retention_after": after,
               "per_cell_retention_brier_regression": [b["normalized_brier"] - a["normalized_brier"] for a, b in zip(before, after)],
               "ood_confidence_false_accept_rate": {arm: sum(v) / len(v) for arm, v in ood.items()},
               "ood_thresholds_from_historical_calibration_only": thresholds,
               "local_source_task_clusters": cells, "iid_event_sample_claimed": False,
               "work_ledger": [setup_work, trial_work], "online_update_wall_seconds_inside_trial": train_seconds,
               "online_update_time_not_additionally_charged": True,
               "real_pretrained_or_hepta_learning_qualified": False, "production_promotion_permitted": False}
    write_jsonl_once(root / "updates.jsonl", records)
    write_jsonl_once(root / "outcomes.jsonl", outcomes)
    write_once(root / "summary.json", summary)
    return summary


NODES = 16


def graph_case(rng, length, family="new_composition", *, blocked=False):
    """Oracle uses observed directed edges; 'unknown' means missing evidence."""
    require(type(length) is int and 1 <= length < NODES, "invalid bounded graph length")
    require(family in TASKS and type(blocked) is bool, "unknown graph family or blocked flag")
    perm = rng.permutation(NODES)
    path = perm[:length + 1]
    a = np.zeros((NODES, NODES), dtype=np.float32)
    for x, y in zip(path[:-1], path[1:]):
        a[x, y] = 1
    # Distractors contain no shortcut into the query chain.
    extra = perm[length + 1:]
    for x, y in zip(extra[:-1], extra[1:]):
        if rng.random() < .6:
            a[x, y] = 1
    start, goal = int(path[0]), int(path[-1])
    complete = True
    hint = np.zeros(NODES, dtype=np.float32)
    hint[int(rng.integers(NODES))] = 1
    if blocked:
        cut = int(rng.integers(length))
        a[path[cut], path[cut + 1]] = 0
    if family == "temporal_order":
        # Reversing observed temporal precedence reverses reachability.
        a = a.T.copy()
        start, goal = goal, start
    elif family == "missing_evidence":
        complete = False
        # An observed intact path supports YES despite other missing evidence.
        # A broken observed path with incomplete evidence supports UNKNOWN, not NO.
    elif family == "wrong_hint":
        hint[:] = 0
        hint[goal] = 1
    elif family == "counterfactual":
        if blocked:
            # Restore the actually deleted edge: the intervention now enables a path.
            a[path[cut], path[cut + 1]] = 1
        else:
            a[path[length // 2], path[length // 2 + 1]] = 0
    reach = np.zeros(NODES, dtype=np.float32)
    reach[start] = 1
    trajectory = []
    for _ in range(16):
        reach = np.maximum(reach, (a.T @ reach > 0).astype(np.float32))
        trajectory.append(reach.copy())
    y = 1 if reach[goal] else 0 if complete else 2
    return {"adjacency": a, "start": start, "goal": goal, "hint": hint, "complete": complete,
            "label": y, "oracle_trajectory": np.stack(trajectory), "family": family}


def tensor_graphs(cases):
    adjacency = torch.from_numpy(np.stack([x["adjacency"] for x in cases]))
    start = F.one_hot(torch.tensor([x["start"] for x in cases]), NODES).float()
    hints = torch.from_numpy(np.stack([x["hint"] for x in cases]))
    return adjacency, start, hints


class RecurrentReasoner(nn.Module):
    def __init__(self):
        super().__init__()
        self.cell = nn.Sequential(nn.Linear(4, 16), nn.Tanh(), nn.Linear(16, 1))

    def step(self, adjacency, state, start, hints):
        incoming = torch.bmm(adjacency.transpose(1, 2), state.unsqueeze(-1)).squeeze(-1)
        features = torch.stack((state, incoming, start, hints), dim=-1)
        return torch.maximum(start, torch.sigmoid(self.cell(features).squeeze(-1)))


class FlatReasoner(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(NODES * NODES + 2 * NODES, 64), nn.SiLU(), nn.Linear(64, 4 * NODES))

    def forward(self, adjacency, start, hints):
        return self.net(torch.cat((adjacency.flatten(1), start, hints), 1)).reshape(-1, 4, NODES)


def graph_train(root, *, steps=240):
    root = Path(root)
    configure(SEED + 700)
    rng = np.random.default_rng(SEED + 700)
    train = [graph_case(rng, int(rng.integers(1, 5)), blocked=bool(i % 2)) for i in range(512)]
    adjacency, start, hints = tensor_graphs(train)
    target = torch.from_numpy(np.stack([x["oracle_trajectory"][:4] for x in train]))
    recur, flat = RecurrentReasoner(), FlatReasoner()
    optimizers = [torch.optim.AdamW(m.parameters(), lr=.01) for m in (recur, flat)]
    losses, work = [], []
    # Same generated graph/step supervision, batch order and optimizer-step budget.
    for model_index, model in enumerate((recur, flat)):
        clock0 = clock()
        sampler = torch.Generator().manual_seed(SEED + 999)
        last_loss = None
        for _ in range(steps):
            ix = torch.randint(0, len(train), (32,), generator=sampler)
            a, s, h, y = adjacency[ix], start[ix], hints[ix], target[ix]
            optimizers[model_index].zero_grad(set_to_none=True)
            if model_index == 0:
                state, predictions = s, []
                for _ in range(4):
                    state = recur.step(a, state, s, h)
                    predictions.append(state)
                loss = F.binary_cross_entropy(torch.stack(predictions, 1), y)
            else:
                loss = F.binary_cross_entropy_with_logits(flat(a, s, h), y)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.)
            optimizers[model_index].step()
            last_loss = float(loss.detach())
        model.eval()
        work.append(measured_work("graph/" + ("recurrent" if model_index == 0 else "feedforward") + "-training", "training", clock0))
        losses.append(last_loss)
    for label, model in (("recurrent", recur), ("feedforward", flat)):
        np.savez(root / (label + "-weights.npz"), **{k: v.detach().numpy() for k, v in model.state_dict().items()})
    return recur, flat, {"training_graphs": len(train), "max_training_path_length": 4,
                          "same_step_level_supervision": True, "same_optimizer_steps": steps,
                          "actual_parameters": [sum(p.numel() for p in m.parameters()) for m in (recur, flat)],
                          "final_training_losses": losses, "work_ledger": work,
                          "actual_training_compute_equal_claimed": False}


def classify(state, case):
    p = float(state[0, case["goal"]])
    # Deterministic evidence-completeness guard is available to ALL policies.
    return [1 - p, p, 0.] if case["complete"] else [0., p, 1 - p]


def activation_trace(depth):
    return [{"event_id": f"activation-{i}", "activation_id": f"iteration-{i}", "kind": "cell",
             "parents": [] if i == 0 else [f"activation-{i - 1}"]} for i in range(depth)]


def run_graph_model(recur, flat, case, arm):
    t = clock()
    a, s, h = tensor_graphs([case])
    with torch.no_grad():
        if arm == "feedforward":
            state = flat(a, s, h).sigmoid()[:, -1]
            depth = 1
        else:
            depth = int(arm)
            state = s
            for _ in range(depth):
                state = recur.step(a, state, s, h)
        p = classify(state, case)
    timing = measured_work("unused", "inference", t)
    return p, timing, causal_depth(activation_trace(depth))


def reasoning_probe(root, recur, flat, *, programs=48):
    root = Path(root)
    rng = np.random.default_rng(SEED + 800)
    cases = []
    for i in range(programs):
        for family in TASKS:
            # New permutations and longer paths than the training support.
            case = graph_case(rng, int(rng.integers(5, 13)), family, blocked=bool(i % 2))
            case["case_id"], case["program_root"] = f"heldout-{i}/{family}", f"generated-root-{i}"
            cases.append(case)
    arms = ["1", "2", "4", "8", "16", "feedforward"]
    records = []
    for i, case in enumerate(cases):
        ordered = arms[i % len(arms):] + arms[:i % len(arms)]
        for arm in ordered:
            p, timing, depth = run_graph_model(recur, flat, case, arm)
            records.append({"case_id": case["case_id"], "program_root": case["program_root"],
                            "family": case["family"], "arm": arm, "probabilities": p,
                            "oracle_label": case["label"], "input_digest": digest([case["adjacency"].tolist(), case["start"], case["goal"], case["hint"].tolist(), case["complete"]]),
                            "work": dict(timing, physical_work_id=case["case_id"] + "/" + arm), "depth": depth,
                            "controlled_generated_oracle": True})
    summary = {}
    for family in TASKS:
        summary[family] = {}
        for arm in arms:
            rows = [r for r in records if r["family"] == family and r["arm"] == arm]
            summary[family][arm] = {**metrics([r["probabilities"] for r in rows], [r["oracle_label"] for r in rows]),
                                    "latency": latency([1000 * r["work"]["wall_seconds"] for r in rows]),
                                    "cpu_seconds": sum(r["work"]["cpu_seconds"] for r in rows),
                                    "observed_depth": max(r["depth"]["sequential_cell_depth"] for r in rows)}
    report = {"schema": "hepta.controlled-reasoning-probe.v1", "test_program_roots": programs,
              "test_cases": len(cases), "actual_answer_executions": len(records), "families": summary,
              "same_available_graph_information": True, "same_actual_compute_claimed": False,
              "larger_feedforward_control_included": True, "message_passing_inductive_bias_explicit": True,
              "independent_future_calendar_windows": False, "production_promotion_permitted": False}
    write_jsonl_once(root / "reasoning-observations.jsonl", records)
    write_once(root / "reasoning-summary.json", report)
    return cases, report


def decision_tree(p_now, p_later, cost):
    return {"root": {"actions": [
        {"id": "stop", "duration": 0, "cost": 0, "successors": [{"node": "yes", "probability": p_now}, {"node": "no", "probability": 1-p_now}]},
        {"id": "continue", "duration": 1, "cost": cost, "successors": [{"node": "yes", "probability": p_later}, {"node": "no", "probability": 1-p_later}]}]},
        "yes": {"terminal": 1.}, "no": {"terminal": 0.}}


def ndu_probe(root, recur, cases):
    """Adaptive compute against calibration-only value models; no test-label lookahead.

    Finite-scenario recursive-risk profile, not a learned stochastic FBSDE. The
    cost price and maximal depth are frozen in the protocol, before calibration.
    """
    root = Path(root)
    max_depth, marginal_step_price, risk_base = 16, .008, 1.
    rng = np.random.default_rng(SEED + 900)
    calibration = [graph_case(rng, int(rng.integers(1, 13)), TASKS[i % len(TASKS)], blocked=bool(i % 2)) for i in range(240)]
    table = defaultdict(list)
    calibration0 = clock()
    with torch.no_grad():
        for case in calibration:
            a, s, h = tensor_graphs([case])
            state, observations = s, []
            for depth in range(1, max_depth + 1):
                state = recur.step(a, state, s, h)
                p = classify(state, case)
                win = max(range(3), key=p.__getitem__)
                observations.append((depth, min(9, int(max(p) * 10)), float(win == case["label"])))
            terminal = observations[-1][2]
            for depth, confidence_bin, correct in observations:
                table[(depth, confidence_bin)].append((correct, terminal))
    estimates = {key: ((sum(x for x, _ in rows) + 1) / (len(rows) + 2),
                       (sum(y for _, y in rows) + 1) / (len(rows) + 2), len(rows)) for key, rows in table.items()}
    # Compile immutable value/stop tables once per frozen critic/model/objective.
    # The full state used by this registered controller is (depth, confidence bin).
    # A richer profile must extend its key; this is not a generic NDU cache rule.
    policy_cache = {arm: {} for arm in NDU_ARMS[2:]}
    equivalence_errors = []
    for (depth, confidence_bin), (p0, p1, support) in estimates.items():
        if support < 8:
            continue
        for arm in policy_cache:
            risk = 0. if arm == "deterministic_ndu" else risk_base + .5 * depth / max_depth
            tree = decision_tree(p0, p1, marginal_step_price * (max_depth - depth))
            value, policy = recursive_value(tree, "root", risk=risk)
            selected = policy["root"]
            if arm == "generic_nested_risk":
                equivalent = generic_nested_risk(tree, "root", risk=risk)
                equivalence_errors.append(abs(value - equivalent))
                alternatives = {a["id"]: generic_nested_risk(dict(tree, root={"actions": [a]}), "root", risk=risk)
                                for a in tree["root"]["actions"]}
                selected = min(alternatives, key=lambda name: (-alternatives[name], name))
            policy_cache[arm][(depth, confidence_bin)] = selected
    cache_record = {"model_digest": weights_digest(recur), "profile": "finite-scenario-stopping-v1",
                    "max_depth": max_depth, "step_price": marginal_step_price, "risk_base": risk_base,
                    "scope": "controlled-group/research-only",
                    "policies": {arm: {str(k): v for k, v in entries.items()} for arm, entries in policy_cache.items()}}
    cache_digest = digest(cache_record)
    calibration_work = measured_work("ndu/shared-critic-calibration-and-cache", "training", calibration0)
    write_once(root / "ndu-policy-cache.json", dict(cache_record, cache_digest=cache_digest))
    rows = []
    for index, case in enumerate(cases):
        for arm in NDU_ARMS:
            started = clock()
            a, s, h = tensor_graphs([case])
            state, unsupported, selected = s, 0, "continue"
            with torch.no_grad():
                for depth in range(1, max_depth + 1):
                    state = recur.step(a, state, s, h)
                    p = classify(state, case)
                    if arm == "fixed_budget":
                        stop = depth == max_depth
                    elif arm == "confidence":
                        stop = max(p) >= .95 or depth == max_depth
                    else:
                        lookup = estimates.get((depth, min(9, int(max(p) * 10))))
                        if lookup is None or lookup[2] < 8:
                            unsupported += 1
                            stop = depth == max_depth
                        else:
                            selected = policy_cache[arm][(depth, min(9, int(max(p) * 10)))]
                            stop = selected == "stop" or depth == max_depth
                    if stop:
                        break
                p = classify(state, case)
            timing = measured_work(case["case_id"] + "/" + arm, "inference", started)
            # Evaluate only AFTER the policy has committed its final compute depth.
            correct = max(range(3), key=p.__getitem__) == case["label"]
            rows.append({"case_id": case["case_id"], "program_root": case["program_root"], "family": case["family"],
                         "arm": arm, "depth": depth, "probabilities": p, "external_generated_correct": correct,
                         "registered_step_cost": depth * marginal_step_price,
                         "external_step_cost_adjusted_score": float(correct) - depth * marginal_step_price,
                         "measured_work": timing, "unsupported_critic_lookups": unsupported,
                         "selected_compute_action": selected, "controlled_generated_oracle": True})
    summaries = {}
    for arm in NDU_ARMS:
        records = [r for r in rows if r["arm"] == arm]
        summaries[arm] = {"executions": len(records), "accuracy": sum(r["external_generated_correct"] for r in records) / len(records),
                          "mean_depth": sum(r["depth"] for r in records) / len(records),
                          "mean_registered_step_cost_adjusted_score": sum(r["external_step_cost_adjusted_score"] for r in records) / len(records),
                          "cpu_seconds": sum(r["measured_work"]["cpu_seconds"] for r in records),
                          "latency": latency([1000 * r["measured_work"]["wall_seconds"] for r in records]),
                          "max_depth_cap_met": all(r["depth"] <= max_depth for r in records)}
    matches = all(a["depth"] == b["depth"] for a, b in zip(
        [r for r in rows if r["arm"] == "recursive_risk_ndu"], [r for r in rows if r["arm"] == "generic_nested_risk"]))
    report = {"schema": "hepta.controlled-ndu-probe.v1", "arms": summaries,
              "valuation_implementation": "frozen-critic-model-objective-policy-table-v2",
              "policy_cache_digest": cache_digest,
              "policy_cache_entries": sum(len(x) for x in policy_cache.values()),
              "critic_calibration_cases": len(calibration), "calibration_work": calibration_work,
              "calibration_work_charged_once_not_per_episode": True,
              "heldout_policy_does_not_read_oracle_labels": True,
              "finite_scenario_recursive_risk_profile": True,
              "general_stochastic_fbsde_implemented": False,
              "registered_step_cost_is_not_measured_energy_or_cpu": True,
              "measured_runtime_costs_reported_separately": True,
              "generic_control_depth_equivalence": matches,
              "generic_value_max_absolute_error": max(equivalence_errors, default=0.),
              "ndu_exclusive_advantage_claimed": False, "production_promotion_permitted": False}
    write_jsonl_once(root / "ndu-observations.jsonl", rows)
    write_once(root / "ndu-summary.json", report)
    return report


def run(root, smoke=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    configure()
    protocol = {"schema": "hepta.controlled-four-gate-learning-protocol.v1", "seed": SEED,
                "few_shots": [8, 32, 128] if not smoke else [8], "cells": 12 if not smoke else 3,
                "events_per_cell": 128 if not smoke else 8, "graph_optimizer_steps": 240 if not smoke else 10,
                "held_out_graph_program_roots": 48 if not smoke else 3,
                "depths": [1, 2, 4, 8, 16], "same_supervision_feedforward_control": True,
                "ndu_max_depth": 16, "ndu_per_step_price": .008,
                "ndu_confidence_threshold": .95, "ndu_risk_base": 1.,
                "input_origin": "generated_controlled_tasks_not_hepta_data",
                "pretrained_model_loaded": False, "production_promotion_permitted": False}
    write_once(root / "protocol.json", protocol)
    write_once(root / "environment.json", {"python": sys.version, "torch": torch.__version__, "numpy": np.__version__,
                                           "threads": 1, "cuda_available": torch.cuda.is_available(), "device": "cpu"})
    for shots in protocol["few_shots"]:
        result = cell_probe(root / f"cell-{shots}", shots, cells=protocol["cells"], events_per_cell=protocol["events_per_cell"])
        print("cell", shots, {k: round(v["accuracy"], 4) for k, v in result["metrics"].items()}, flush=True)
    recur, flat, training = graph_train(root, steps=protocol["graph_optimizer_steps"])
    write_once(root / "graph-training.json", training)
    cases, reasoning = reasoning_probe(root, recur, flat, programs=protocol["held_out_graph_program_roots"])
    ndu = ndu_probe(root, recur, cases)
    write_once(root / "completion.json", {"status": "controlled_cpu_experiments_executed", "protocol_digest": digest(protocol),
                                          "reasoning_answer_executions": reasoning["actual_answer_executions"],
                                          "ndu_answer_executions": sum(v["executions"] for v in ndu["arms"].values()),
                                          "hepta_learning_or_reasoning_qualified": False, "production_promotion_permitted": False})
    return ndu


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    result = run(args.output, args.smoke)
    print({k: round(v["accuracy"], 4) for k, v in result["arms"].items()})
