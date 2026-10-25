"""Causal paired-policy forks; commit public decisions before future draws.

Batched branches can compute unused rows. Their cost is counterfactual execution
cost, never single-policy latency. Only selected actual media receive outcomes.
"""

from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch

from ..abc_recovery.base_recovery import file_sha, write_json
from ..abc_recovery.control import PLANS, load_feedback
from ..abc_recovery.runtime import ACTIONS, initialize, public_features, public_frame, transition
from ..abc_recovery.trees import METRICS, _source_identity
from .compact_tree import decode_media, encode_media, owner_rng, paired_batch, scores
from .observability import input_evidence, observed_features
from .settings import FIXED_PLAN, OLD
from .value import features


POLICIES = ("fixed", "static", "one_shot", "feedback", "legacy")


@torch.inference_mode()
def public_vector(model, run, controller, sensor, evidence, work):
    if controller.mode == "enriched":
        return observed_features(model, public_frame(run), sensor=sensor, evidence=evidence, work=work)
    base = public_features(model, public_frame(run), work=work)
    return torch.cat((base[:, :-1], torch.zeros(len(base), 90), base[:, -1:]), 1)


@torch.inference_mode()
def execute_view(snapshot, controller, legacy, sensor, corpus, judges, directory, *, role, start,
                 count, scenarios, training_seed, view, static_index):
    directory.mkdir(parents=True, exist_ok=False)
    batch, observation, target = paired_batch(corpus, role, start, count, scenarios, view)
    model = snapshot._model
    work, feature_work = Counter(), Counter()
    evidence = input_evidence(sensor, observation, feature_work) if controller.mode == "enriched" else None
    root = initialize(model, observation, generator=owner_rng(role, start, training_seed, view, ()))
    root_public = public_vector(model, root, controller, sensor, evidence, feature_work)
    n = len(root.pixels)
    paths = torch.full((n, len(POLICIES)), -1, dtype=torch.long)
    paths[:, 0], paths[:, 1] = PLANS.index(FIXED_PLAN), static_index
    paths[:, 2] = controller.choose_plan(root_public)
    feature_work.update({"one_shot_head_calls": 1, "one_shot_head_examples": n})
    first = torch.zeros_like(paths)
    for p in range(3):
        first[:, p] = torch.tensor([ACTIONS.index(PLANS[i][0]) if PLANS[i] else 0 for i in paths[:, p].tolist()])
    first[:, 3] = controller.choose(root_public, 2)
    first[:, 4] = legacy.choose(features(root_public, "base"), 2)
    feature_work.update({"new_feedback_head_calls": 1, "new_feedback_head_examples": n,
                         "legacy_feedback_head_calls": 1, "legacy_feedback_head_examples": n})
    for p in (3, 4):
        paths[first[:, p] == 0, p] = 0
    write_json(directory / "root-decisions.json", {"unix_ns": time.time_ns(), "policies": POLICIES,
        "first_action_indices": first.tolist(), "initial_only_plan_indices": paths[:, :3].tolist(),
        "root_public_sha256": root.ledger[-1]["after_public_sha256"], "future_draws_started": False})
    output_bits = np.empty((n, len(POLICIES), 196), dtype=np.uint8)
    output_tokens = np.empty((n, len(POLICIES), 8), dtype=np.uint8)
    output_hashes = np.empty((n, len(POLICIES)), dtype="S64")
    filled = np.zeros((n, len(POLICIES)), dtype=bool)
    ledger, node_rows, selected_unique_rows = [], 0, 0

    def record(run, plan_index, parent_entries=0):
        nonlocal node_rows, selected_unique_rows
        entries = run.ledger[parent_entries:]
        for item in entries:
            work.update(item.get("work", {}))
        ledger.append({"plan_index": plan_index, "incremental_ledger": entries})
        node_rows += n
        bits, tokens, hashes = encode_media(run.pixels, run.tokens)
        selected = paths == plan_index
        selected_unique_rows += int(selected.any(1).sum())
        for p in range(len(POLICIES)):
            mask = selected[:, p].numpy()
            output_bits[mask, p], output_tokens[mask, p], output_hashes[mask, p] = bits[mask], tokens[mask], hashes[mask]
            filled[mask, p] = True

    record(root, 0)
    for action in range(1, 5):
        if not (first == action).any():
            continue
        first_path = (ACTIONS[action],)
        child = transition(model, root, first_path[0], generator=owner_rng(role, start, training_seed, view, first_path))
        child_public = public_vector(model, child, controller, sensor, evidence, feature_work)
        decisions = {}
        for p in (3, 4):
            ids = torch.nonzero(first[:, p] == action).flatten()
            if len(ids):
                second = (controller.choose(child_public[ids], 1) if p == 3
                          else legacy.choose(features(child_public[ids], "base"), 1))
                paths[ids, p] = torch.where(second == 0, action, 5 + (action - 1) * 4 + second - 1)
                label = "new" if p == 3 else "legacy"
                feature_work.update({label + "_feedback_head_calls": 1, label + "_feedback_head_examples": len(ids)})
                decisions[POLICIES[p]] = {"rows": ids.tolist(), "second_action_indices": second.tolist()}
        write_json(directory / f"child-{action}-decisions.json", {"unix_ns": time.time_ns(),
            "parent_path": first_path, "public_sha256": child.ledger[-1]["after_public_sha256"],
            "feedback_decisions": decisions, "grandchild_draws_started": False})
        record(child, action, len(root.ledger))
        for second in range(1, 5):
            index = 5 + (action - 1) * 4 + second - 1
            if not (paths == index).any():
                continue
            path = (*first_path, ACTIONS[second])
            terminal = transition(model, child, path[-1], generator=owner_rng(role, start, training_seed, view, path))
            record(terminal, index, len(child.ledger))
    if (paths < 0).any() or not filled.all():
        raise ValueError("A frozen policy failed to commit a complete path/output")
    write_json(directory / "generation-ledger.json", {"nodes": ledger, "no_ancestor_work_resummed": True,
        "generation_work": dict(work), "feature_work": dict(feature_work),
        "computed_node_rows": node_rows, "selected_unique_terminal_rows": selected_unique_rows,
        "batched_unused_counterfactual_rows_included_in_work": node_rows - selected_unique_rows})
    media_path = directory / "selected-media.npz"
    with media_path.open("xb") as stream:
        np.savez_compressed(stream, pixels_bits=output_bits, tokens=output_tokens,
                            output_sha256=output_hashes, plan_indices=paths.numpy())
    result = {name: {metric: torch.empty((n, len(POLICIES))) for metric in METRICS} for name in judges}
    with np.load(media_path, allow_pickle=False) as saved:
        bits, tokens, hashes = saved["pixels_bits"], saved["tokens"], saved["output_sha256"]
        for p in range(len(POLICIES)):
            pixels, _, captions = decode_media(bits[:, p], tokens[:, p], hashes[:, p])
            observed = scores(judges, pixels, captions, target)
            for name in judges:
                for metric in METRICS:
                    result[name][metric][:, p] = observed[name][metric]
    summary = {"media_file_sha256": file_sha(media_path), "node_rows": node_rows,
               "selected_policy_rows": n * len(POLICIES), "selected_unique_terminal_rows": selected_unique_rows,
               "generation_work": dict(work), "feature_work": dict(feature_work),
               "actual_media_reopened_before_scoring": True,
               "first_decisions_before_children": True, "second_decisions_before_grandchildren": True}
    write_json(directory / "summary.json", summary)
    return paths, result, batch.source_ids, summary


@torch.inference_mode()
def execute_model(snapshot, controller, sensor, corpus, judges, directory, *, role, start,
                  count, scenarios, training_seed, arm, static_index, views):
    directory.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    legacy_path = OLD / f"control-001/seed-{training_seed}/{arm}/policies/feedback.pt"
    legacy = load_feedback(legacy_path)
    identity = _source_identity(corpus, role, start, count)
    write_json(directory / "registration.json", {"schema": "hepta.abc-next.causal-execution.v1",
        "unix_ns": time.time_ns(), "role": role, "start": start, "count": count, "scenarios": scenarios,
        "training_seed": training_seed, "arm": arm, "source_identity": identity,
        "model_sha256": snapshot.fingerprint, "legacy_sha256": file_sha(legacy_path),
        "static_index": static_index, "policies": POLICIES, "entrypoint_sha256": file_sha(Path(__file__))})
    data = {"cases": [], "views": [], "scenarios": [], "source_ids": [], "paths": [],
            "policies": POLICIES, "metrics": {name: {metric: [] for metric in METRICS} for name in judges}}
    summaries = {}
    for view in views:
        paths, metrics, ids, summary = execute_view(snapshot, controller, legacy, sensor, corpus, judges,
            directory / view, role=role, start=start, count=count, scenarios=scenarios,
            training_seed=training_seed, view=view, static_index=static_index)
        data["paths"].append(paths)
        summaries[view] = summary
        for name in judges:
            for metric in METRICS:
                data["metrics"][name][metric].append(metrics[name][metric])
        for case in range(count):
            for scenario in range(scenarios):
                data["cases"].append(start + case)
                data["views"].append(view)
                data["scenarios"].append(scenario)
                data["source_ids"].append(ids[case])
    data["paths"] = torch.cat(data["paths"])
    for name in judges:
        for metric in METRICS:
            data["metrics"][name][metric] = torch.cat(data["metrics"][name][metric])
    snapshot.verify_integrity()
    with (directory / "data.pt").open("xb") as stream:
        torch.save(data, stream)
    write_json(directory / "summary.json", {"schema": "hepta.abc-next.causal-execution-result.v1",
        "status": "completed", "source_identity": identity, "independent_source_pairs": count,
        "data_sha256": file_sha(directory / "data.pt"), "views": summaries,
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "timing_scope": "batched paired-policy causal forks, persistence, reopening and both offline judges; not deployment latency"})
    return data
