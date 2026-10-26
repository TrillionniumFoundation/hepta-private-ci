"""Actual paired requests, followed by private same-state H1 counterfactuals."""

import argparse
from collections import Counter
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_followup.control.features import ExactFeatureCache
from ...abc_next.compact_tree import scores
from ...abc_next.sensor_run import load_sensor
from ...abc_next.value import load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.runtime import ACTIONS, initialize, public_digest, public_frame, transition
from ...abc_recovery.trees import stable_seed
from ...closure_20261025.control.registry import asset_pins, load_model
from ...closure_20261025.control.rollout import decode, emit_json
from ...v6.data import Observation, Target
from ...v7.data import VIEWS, make_batch
from ...v7.evaluation import load_reward
from ..control.run import payload, persist, moments
from .model import load


POLICIES = ("cached_teacher", "rich_paired")


def finite_vector(value):
    return [float(x) if torch.isfinite(x) else None for x in value[0]]


@torch.inference_mode()
def request(model, observation, teacher, candidate, sensor, *, policy, seed, case, view, draw, spec, media, commitments):
    if type(observation) is not Observation or policy not in POLICIES: raise ValueError("Registered public request required")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    row = dict(seed=seed, case=case, view=view, draw=draw, policy=policy, status="failed")
    work, decisions, path, diagnostic = Counter(), [], [], None
    run, root_draft = None, None
    try:
        run = initialize(model, observation, generator=torch.Generator().manual_seed(stable_seed(spec["initial_namespace"], seed, case, view)))
        cache = ExactFeatureCache(model, sensor, observation, work)
        while not run.done:
            frame = public_frame(run); full = cache.read(frame)
            if root_draft is None: root_draft = payload(frame.pixels, frame.tokens)
            if policy == "cached_teacher":
                value = moments(teacher, full, frame.remaining)
                delta = value - value[:, :1]; chosen = int(value.argmin(-1)[0])
                work["teacher_calls"] += 1
            else:
                delta = candidate.predict(full, frame.remaining); chosen = int(delta.argmin(-1)[0])
                work["paired_difference_head_calls"] += 1
            detail = {"decision_index": len(decisions), "remaining": frame.remaining, "action": ACTIONS[chosen],
                      "public_sha256": public_digest(frame), "predicted_action_differences": finite_vector(delta)}
            # The owner may retain this immutable pre-innovation state for
            # diagnostics. The policy receives only the current public vector.
            if policy == "rich_paired" and frame.remaining == 1:
                diagnostic = (run, full.detach().clone(), tuple(path), finite_vector(delta))
            emit_json(commitments, {**row, **detail}); decisions.append(detail)
            future = torch.Generator().manual_seed(stable_seed(spec["future_namespace"], seed, case, view, draw, tuple((*path, ACTIONS[chosen]))))
            run = transition(model, run, ACTIONS[chosen], generator=future)
            if chosen: path.append(ACTIONS[chosen])
            if len(decisions) > 2: raise ValueError("H2 budget exceeded")
        row.update({"status": "completed", "terminal": persist(media, payload(run.pixels, run.tokens))})
    except Exception as error:
        row["error"] = {"type": type(error).__name__, "message": str(error)}
    if run is not None:
        for entry in run.ledger: work.update(entry.get("work", {}))
    row.update({"wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
                "path": path, "decisions": decisions, "work": dict(work)})
    if root_draft is not None: row["root_stop"] = persist(media, root_draft)
    return row, diagnostic


@torch.inference_mode()
def counterfactuals(model, teacher, diagnostic, selected, spec, media, commitments):
    """Offline owner branch evaluation, after the actual selected action ends."""
    parent, public, prefix, prediction = diagnostic
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = public_digest(public_frame(parent))
    old_moment = moments(teacher, public, 1)
    teacher_delta = finite_vector(old_moment - old_moment[:, :1])
    alternatives, work = [], Counter()
    for action in ACTIONS:
        if action == selected["decisions"][-1]["action"]:
            alternatives.append({"action": action, "media": selected["terminal"], "reused_actual_selected_result": True})
            continue
        emit_json(commitments, {**{k: selected[k] for k in ("seed", "case", "view", "draw")},
            "phase": "offline_counterfactual_action_committed", "action": action,
            "parent_public_sha256": before, "actual_selected_action_already_completed": True})
        future = torch.Generator().manual_seed(stable_seed(spec["future_namespace"], selected["seed"], selected["case"], selected["view"], selected["draw"], tuple((*prefix, action))))
        run = transition(model, parent, action, generator=future)
        for entry in run.ledger[len(parent.ledger):]: work.update(entry.get("work", {}))
        alternatives.append({"action": action, "media": persist(media, payload(run.pixels, run.tokens)), "reused_actual_selected_result": False})
    return {**{k: selected[k] for k in ("seed", "case", "view", "draw")}, "parent_public_sha256": before,
        "selected_action": selected["decisions"][-1]["action"], "prediction": prediction,
        "old_teacher_prediction_same_public_state": teacher_delta, "alternatives": alternatives,
        "offline_wall_ns": time.perf_counter_ns() - wall, "offline_cpu_ns": time.process_time_ns() - cpu,
        "work": dict(work), "not_visible_to_policy": True}


def verify_pins(spec):
    for path, digest in spec["frozen_candidate_sha256"].items():
        if file_sha(Path(path)) != digest: raise ValueError("Frozen input differs: " + path)


def run(asset, protocol, output):
    specification = json.loads(protocol.read_text()); verify_pins(specification)
    actual_assets = asset_pins(asset.resolve())
    if any(specification["frozen_candidate_sha256"].get(path) != digest for path, digest in actual_assets.items()):
        raise ValueError("Actual command asset root is not the protocol-bound model/sensor/observer root")
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    write_json(output / "registration.json", {"protocol_sha256": file_sha(protocol), "spec": specification, "started_unix_ns": time.time_ns()})
    source = specification["source"]
    loader = importlib.import_module(source["loader"])
    corpus = loader.load_registered(Path(source["cache"]), Path(source["allocation"]), protocol, "action_value")
    count = source["pairs"]
    observations, targets, identities = {}, {}, {}
    for view in VIEWS:
        batch = make_batch(corpus, source["role"], count, stable_seed(specification["evaluation"]["observation_namespace"], count), view=view, offset=0)
        for case in range(count):
            observations[view, case] = Observation(*(getattr(batch.observation, key)[case:case + 1].clone() for key in ("pixels", "mask", "text_tokens")))
            targets[view, case] = Target(*(getattr(batch.target, key)[case:case + 1].clone() for key in ("pixels", "text_tokens", "labels")))
            identities[case] = batch.source_ids[case]
    sensor = load_sensor(asset / "abc3-runs/public-sensor-001/sensor.pt")
    observers = {name: load_reward(asset / path, expected_file_sha256=digest)[0] for name, path, digest in (
        ("primary", "abc2-runs/base-recovery-001/reward-observer.pt", "8cfca1b0cd0a69bcfcc6a9d34d0a672c07c28f3342823ef8a3f6763e9430a003"),
        ("secondary", "abc2-runs/qualification-001/secondary-observer.pt", "b0851ce56189d159b53449cfc914cf84b9b63e82a6f0050228096666752595fe"))}
    rng = np.random.default_rng(specification["evaluation"]["order_seed"])
    requests, failed, diagnostic_count, loads, offline_wall, offline_cpu = 0, 0, 0, [], 0, 0
    with (output / "media.bin").open("x+b") as media, gzip.open(output / "requests.jsonl.gz", "xt", compresslevel=3) as request_log, gzip.open(output / "commitments.jsonl.gz", "xt", compresslevel=3) as commitments, gzip.open(output / "counterfactuals.jsonl.gz", "xt", compresslevel=3) as diagnostic_log, gzip.open(output / "diagnostic-commitments.jsonl.gz", "xt", compresslevel=3) as diagnostic_commitments:
        for selected in specification["candidates"]:
            seed = selected["seed"]; started = time.perf_counter_ns()
            snapshot = load_model(asset, seed)
            teacher = load_controller(asset / f"abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt")
            candidate = load(Path(selected["checkpoint"]))
            loads.append({"seed": seed, "wall_ns": time.perf_counter_ns() - started})
            for view in VIEWS:
                for case in range(count):
                    for draw in range(specification["draws"]):
                        diagnostic, candidate_row = None, None
                        for index, policy in enumerate(rng.permutation(POLICIES).tolist()):
                            row, retained = request(snapshot._model, observations[view, case], teacher, candidate, sensor,
                                policy=policy, seed=seed, case=case, view=view, draw=draw,
                                spec=specification["evaluation"], media=media, commitments=commitments)
                            row.update({"order_index": index, "source_ids": identities[case]})
                            emit_json(request_log, row); requests += 1; failed += row["status"] != "completed"
                            if policy == "rich_paired": diagnostic, candidate_row = retained, row
                        if diagnostic is not None and candidate_row["status"] == "completed":
                            item = counterfactuals(snapshot._model, teacher, diagnostic, candidate_row, specification["evaluation"], media, diagnostic_commitments)
                            emit_json(diagnostic_log, item); diagnostic_count += 1
                            offline_wall += item["offline_wall_ns"]; offline_cpu += item["offline_cpu_ns"]
                print(json.dumps({"seed": seed, "view": view, "requests": requests, "failures": failed, "H1_counterfactual_nodes": diagnostic_count}), flush=True)
            snapshot.verify_integrity()
    scoring_start = time.perf_counter_ns()
    with (output / "media.bin").open("rb") as media:
        def observe(saved, target):
            media.seek(saved["offset"]); raw = media.read(204)
            if hashlib.sha256(raw).hexdigest() != saved["sha256"]: raise ValueError("Closed actual media changed")
            pixels, _, captions = decode(raw)
            return {name: {key: float(value[0]) for key, value in values.items()} for name, values in scores(observers, pixels, captions, target).items()}
        with gzip.open(output / "requests.jsonl.gz", "rt") as source_log, gzip.open(output / "scored.jsonl.gz", "xt", compresslevel=3) as scored:
            for row in map(json.loads, source_log):
                record = {k: row[k] for k in ("seed", "case", "view", "draw", "policy", "status")}
                target = targets[row["view"], row["case"]]
                if row["status"] == "completed": record["scores"] = observe(row["terminal"], target)
                if "root_stop" in row: record["root_stop_scores"] = observe(row["root_stop"], target)
                scored.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            scored.flush(); os.fsync(scored.fileno())
        with gzip.open(output / "counterfactuals.jsonl.gz", "rt") as source_log, gzip.open(output / "counterfactual-scored.jsonl.gz", "xt", compresslevel=3) as scored:
            for row in map(json.loads, source_log):
                target = targets[row["view"], row["case"]]
                row["outcomes"] = [{"action": item["action"], "scores": observe(item["media"], target)} for item in row["alternatives"]]
                scored.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            scored.flush(); os.fsync(scored.fileno())
    verify_pins(specification)
    if requests != count * len(VIEWS) * specification["draws"] * len(specification["candidates"]) * 2:
        raise ValueError("Registered request census differs")
    write_json(output / "completion.json", {"status": "completed", "requests": requests, "failures": failed, "source_pairs": count,
        "H1_counterfactual_nodes": diagnostic_count, "counterfactual_actions_per_node": 5,
        "offline_counterfactual_wall_ns": offline_wall, "offline_counterfactual_cpu_ns": offline_cpu,
        "scoring_wall_ns": time.perf_counter_ns() - scoring_start, "model_loads": loads,
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "files_sha256": {p.name: file_sha(p) for p in output.iterdir() if p.is_file()}, "completed_unix_ns": time.time_ns()})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--asset-root", type=Path, required=True); p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); run(a.asset_root, a.protocol, a.output)
