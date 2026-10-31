"""Matched new generator continuations on physically reopened actual emissions."""

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.runtime import initialize, transition
from ...abc_next.compact_tree import decode_media, encode_media
from ...abc_next.settings import CACHE, MANIFEST, MANIFEST_SHA, REPO, SEEDS, model_path, observers
from ...v6.data import Observation, Target
from ...v6.neural import parameter_hash
from ...v6.observer import observe_tensors
from ...v7.data import make_batch
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .objective import ARMS, DualState, objective


RUNS = REPO.parent / "abc4-training-runs"
PLAN = ("refine_image", "refine_text")


def source_pins():
    area = REPO / "experiments/multimodal_output_portfolio"
    files = [Path(__file__), Path(__file__).with_name("objective.py"),
             Path(__file__).parents[1] / "process.py"]
    for directory, names in (("abc_recovery", ("runtime", "emission", "base_recovery")),
                             ("abc_next", ("settings", "compact_tree")),
                             ("v6", ("data", "neural", "observer")),
                             ("v7", ("data", "model", "snapshot", "sources", "evaluation"))):
        files.extend(area / directory / (name + ".py") for name in names)
    return {str(p.relative_to(REPO)): file_sha(p) for p in files}


def freeze(path, output, *, steps, seeds):
    if file_sha(MANIFEST) != MANIFEST_SHA or steps < 1 or not set(seeds) <= set(SEEDS):
        raise ValueError("Invalid fixed source/training census")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"schema": "hepta.abc4.actual-generator-training.v1",
        "unix_ns": time.time_ns(), "output": str(output.resolve()),
        "steps": steps, "conditions": 16, "scenarios": 8, "threads": 2,
        "learning_rate": .0001, "gamma": 2., "auxiliary_weight": .05,
        "dual_initial": 0., "dual_rate": .1, "dual_cap": 5.,
        "seeds": list(seeds), "arms": ARMS, "plan": PLAN,
        "source_role": "train", "manifest_sha256": MANIFEST_SHA,
        "source_sha256": source_pins(),
        "warm_start_sha256": {str(s): file_sha(model_path(s, "output_mean")) for s in seeds},
        "primary_observer_sha256": file_sha(REPO.parent / "abc2-runs/base-recovery-001/reward-observer.pt"),
        "objective": "F_gamma(-actual_utility) + .05 supervised; constrained arm additionally dual * actual_failure",
        "constraint": "E failure(candidate) <= E failure(frozen mean warm start), zero margin",
        "constraint_certificate_claimed": False,
        "dual_update": "project(lambda_old + .1*(batch_failure - independent_reference_batch_failure), [0,5]); use lambda_old in current primal step",
        "reference_cost_matched_in_every_arm": True,
        "model_selection": "last fixed update; no outcome-based checkpoint choice",
        "batch_seed": "202610260000 + seed*1000003 + step",
        "candidate_draw_seed": "202610270000 + seed*1000033 + step",
        "reference_draw_seed": "202610280000 + seed*1000037 + step",
        "formal_holdout_opened": False,
        "raw_archival_required": False})
    print(json.dumps({"protocol": str(path), "sha256": file_sha(path)}), flush=True)


def verify(protocol):
    if (protocol["schema"] != "hepta.abc4.actual-generator-training.v1"
            or protocol["source_sha256"] != source_pins()
            or file_sha(MANIFEST) != protocol["manifest_sha256"]
            or tuple(protocol["arms"]) != ARMS or tuple(protocol["plan"]) != PLAN):
        raise ValueError("Training identity differs from its freeze")
    for seed in protocol["seeds"]:
        if file_sha(model_path(seed, "output_mean")) != protocol["warm_start_sha256"][str(seed)]:
            raise ValueError("Matched warm start changed")


def fixed_run(model, observation, seed):
    rng = torch.Generator().manual_seed(seed)
    run = initialize(model, observation, generator=rng)
    for action in PLAN:
        run = transition(model, run, action, generator=rng)
    return run


def persisted_scores(path, candidate, reference, observer, target):
    candidate_data = encode_media(candidate.pixels.detach(), candidate.tokens)
    reference_data = encode_media(reference.pixels, reference.tokens)
    with path.open("xb") as stream:
        np.savez_compressed(stream,
            bits=np.stack((candidate_data[0], reference_data[0])),
            tokens=np.stack((candidate_data[1], reference_data[1])),
            hashes=np.stack((candidate_data[2], reference_data[2])))
        stream.flush()
        os.fsync(stream.fileno())
    result = []
    with np.load(path, allow_pickle=False) as saved:
        for index in range(2):
            pixels, _, captions = decode_media(saved["bits"][index], saved["tokens"][index], saved["hashes"][index])
            rows = observe_tensors(observer, pixels, captions, target.pixels, target.labels)
            utility = torch.tensor([r["utility"] for r in rows], dtype=torch.float32)
            success = torch.tensor([r["caption_valid"] and all(r[k] == 0 for k in
                ("text_fact", "relation", "image_fact", "crossmodal_disagreement")) for r in rows], dtype=torch.bool)
            result.append((utility, success))
    return result, file_sha(path)


def fit_one(protocol, corpus, observer, seed, arm, directory):
    directory.mkdir(parents=True, exist_ok=False)
    raw = directory / "raw"
    raw.mkdir()
    warm = Snapshot.load(model_path(seed, "output_mean"),
                         expected_file_sha256=protocol["warm_start_sha256"][str(seed)])
    model = deepcopy(warm._model).train().requires_grad_(True)
    reference = warm._model
    optimizer = torch.optim.Adam(model.parameters(), lr=protocol["learning_rate"])
    dual = DualState(protocol["dual_initial"])
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    history, chain, schedule = [], hashlib.sha256(), hashlib.sha256()
    conditions, scenarios = protocol["conditions"], protocol["scenarios"]
    n = conditions * scenarios
    with (directory / "steps.jsonl").open("x") as log:
        for step in range(protocol["steps"]):
            batch_seed = 202610260000 + seed * 1000003 + step
            candidate_seed = 202610270000 + seed * 1000033 + step
            reference_seed = 202610280000 + seed * 1000037 + step
            batch = make_batch(corpus, "train", conditions, batch_seed)
            observation = Observation(*(x.repeat_interleave(scenarios, 0) for x in
                (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
            target = Target(*(x.repeat_interleave(scenarios, 0) for x in
                (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
            current = fixed_run(model, observation, candidate_seed)
            with torch.inference_mode():
                baseline = fixed_run(reference, observation, reference_seed)
            measurements, media_sha = persisted_scores(raw / f"step-{step:04d}.npz",
                current, baseline, observer, target)
            utility, success = measurements[0]
            reference_success = measurements[1][1]
            if len(utility) != n:
                raise ValueError("Actual output census differs")
            auxiliary = model.loss(model.decode(current.state, teacher_tokens=target.text_tokens), target)["joint"].mean()
            loss, stats = objective(current.terminal_log_probability.reshape(conditions, scenarios),
                utility.reshape(conditions, scenarios), success.reshape(conditions, scenarios),
                auxiliary, arm=arm, dual=dual, gamma=protocol["gamma"], auxiliary_weight=protocol["auxiliary_weight"])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            gradient_norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), 5.))
            optimizer.step()
            gap = float(reference_success.float().mean() - success.float().mean())
            if arm == "risk_success":
                dual = dual.advance(gap, rate=protocol["dual_rate"], cap=protocol["dual_cap"])
            row = {"step": step + 1, "source_ids": batch.source_ids,
                "batch_seed": batch_seed, "candidate_seed": candidate_seed, "reference_seed": reference_seed,
                "media_sha256": media_sha, "reference_success": float(reference_success.float().mean()),
                "failure_gap": gap, "dual_after_step": dual.value, "gradient_norm_before_clip": gradient_norm,
                **stats}
            encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
            log.write(encoded + "\n")
            chain.update(encoded.encode() + b"\n")
            schedule.update(json.dumps({"step": step, "source_ids": batch.source_ids,
                "batch_seed": batch_seed, "candidate_seed": candidate_seed, "reference_seed": reference_seed},
                sort_keys=True, separators=(",", ":")).encode() + b"\n")
            history.append({k: v for k, v in row.items() if k not in ("source_ids", "media_sha256")})
            if (step + 1) % 100 == 0 or step + 1 == protocol["steps"]:
                log.flush()
                print(json.dumps({"seed": seed, "arm": arm, "step": step + 1,
                    "success": stats["success"], "dual": dual.value}), flush=True)
    metadata = {"source_manifest_sha256": corpus.manifest["manifest_sha256"],
        "schema": "hepta.abc4.actual-generator-model.v1", "arm": arm, "seed": seed,
        "training_steps": protocol["steps"], "warm_parameter_sha256": warm.parameter_sha256,
        "training_source_role": "train", "step_chain_sha256": chain.hexdigest(),
        "training_schedule_sha256": schedule.hexdigest(), "dual_final": dual.value}
    snapshot = Snapshot(model, metadata)
    model_sha = snapshot.save(directory / "model.pt")
    with (directory / "optimizer-final.pt").open("xb") as stream:
        torch.save({"optimizer": optimizer.state_dict(), "dual": dual.value,
            "steps": protocol["steps"], "model_sha256": model_sha}, stream)
    warm.verify_integrity()
    report = {**metadata, "status": "completed", "model_file_sha256": model_sha,
        "model_parameter_sha256": snapshot.parameter_sha256,
        "model_path": str(directory / "model.pt"), "candidate_rows": n * protocol["steps"],
        "reference_rows": n * protocol["steps"], "physical_media_reopened_before_scoring": True,
        "wall_ns": time.perf_counter_ns() - start_wall, "cpu_ns": time.process_time_ns() - start_cpu,
        "final_50_steps": history[-50:], "constraint_verified_on_independent_sources": False}
    write_json(directory / "result.json", report)
    return {k: v for k, v in report.items() if k != "final_50_steps"}


def run(protocol_path):
    protocol = json.loads(protocol_path.read_text())
    verify(protocol)
    output = Path(protocol["output"])
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "registration.json", {"unix_ns": time.time_ns(),
        "protocol_sha256": file_sha(protocol_path), "source_sha256": source_pins()})
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    results = []
    try:
        torch.set_num_threads(protocol["threads"])
        torch.use_deterministic_algorithms(True)
        corpus = load_roles(CACHE, MANIFEST, roles=("train",))
        observer = observers()["primary"]
        observer_before = parameter_hash(observer)
        for seed in protocol["seeds"]:
            for arm in protocol["arms"]:
                results.append(fit_one(protocol, corpus, observer, seed, arm,
                    output / f"seed-{seed}" / arm))
        verify(protocol)
        if parameter_hash(observer) != observer_before:
            raise ValueError("Training observer changed")
        for seed in protocol["seeds"]:
            matched = [x for x in results if x["seed"] == seed]
            if len({x["training_schedule_sha256"] for x in matched}) != 1:
                raise ValueError("Treatment source/draw schedule differs")
        write_json(output / "result.json", {"schema": "hepta.abc4.generator-training-result.v1",
            "status": "completed", "protocol_sha256": file_sha(protocol_path), "models": results,
            "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
            "new_generator_training_executed": True, "formal_holdout_opened": False})
    except BaseException as error:
        write_json(output / "failure.json", {"error": repr(error), "completed_models": results,
            "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=RUNS / "training-001")
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    args = parser.parse_args()
    freeze(args.protocol, args.output, steps=args.steps, seeds=args.seeds) if args.phase == "freeze" else run(args.protocol)


if __name__ == "__main__":
    main()
