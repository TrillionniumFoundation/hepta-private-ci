"""Registered development matrix. No source cohort is a semantic confirmation."""

import argparse
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import platform

import numpy as np
import torch

from .diagnostics import paired_ce_difference
from .model import JointGenerator
from .profile import make_profile
from .training import clock, elapsed, evaluate, inference_controls, pretrain, joint_train, save_model, write


PROTOCOL = Path(__file__).with_name("protocol.json")


def run_cell(output, *, seed=17, width=32, smoke=False):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(PROTOCOL.read_text())
    if seed not in protocol["seeds"] or width not in protocol["widths"]:
        raise ValueError("Unregistered seed/width")
    if smoke:
        protocol.update(pretraining_updates=2, pretraining_batch=2, joint_updates=2,
                        joint_batch=2, development_sources=2, evaluation_draws_per_source=1,
                        bootstrap_replicates=30)
    torch.set_num_threads(protocol["threads"]); torch.use_deterministic_algorithms(True)
    profile = make_profile()
    write(output/"EXECUTED_PROTOCOL.json", protocol); write(output/"PROFILE.json", profile.to_dict())
    result = {"schema": "hepta.joint-generation.v3.factorial-development", "seed": seed, "width": width,
        "smoke": smoke, "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("model.py", "runtime.py", "profile.py", "training.py", "study.py", "diagnostics.py")},
        "runtime": {"python": platform.python_version(), "torch": str(torch.__version__), "threads": protocol["threads"]},
        "profile_sha256": profile.digest, "pretraining": {}, "arms": {}, "inference_controls": {},
        "phase_costs": {}, "comparisons": {}, "confirmation_sources_consumed": 0,
        "research_effect_qualified": False, "natural_semantics_qualified": False}
    begun, bases = clock(), {}
    for mode in protocol["modes"]:
        started = clock(); torch.manual_seed(seed)
        model = JointGenerator(width=width, mode=mode, verify_mode=protocol["verify_mode"])
        training = pretrain(model, protocol, seed)
        checkpoint = save_model(output/mode/"PRETRAINED.pt", model,
            {"stage": "development_supervised", "protocol_sha256": result["protocol_sha256"], "seed": seed})
        result["pretraining"][mode] = {"training": training, "checkpoint": checkpoint}
        result["phase_costs"]["pretraining."+mode] = elapsed(started); bases[mode] = model
        write(output/"PROGRESS.json", result)
        print(json.dumps({"phase": "pretrained", "seed": seed, "width": width, "mode": mode, "checkpoint": str(output/mode/"PRETRAINED.pt")}), flush=True)
    # Randomized arm order is fixed before observing any evaluation returns.
    arms = list(itertools.product(protocol["modes"], protocol["content_training"], protocol["policies"]))
    np.random.default_rng(seed+width*1009).shuffle(arms)
    result["executed_arm_order"] = [".".join(arm) for arm in arms]
    for mode, content, policy in arms:
        arm = ".".join((mode, content, policy)); model = deepcopy(bases[mode]); started = clock()
        training = joint_train(model, content=content, policy=policy, protocol=protocol,
            seed=seed+1000, directory=output/arm/"training", profile=profile)
        result["phase_costs"]["training."+arm] = elapsed(started)
        checkpoint = save_model(output/arm/"MODEL.pt", model,
            {"stage": "development_joint", "arm": arm, "protocol_sha256": result["protocol_sha256"], "seed": seed})
        started = clock()
        evaluation = evaluate(model, output/arm/"analysis", profile,
                              seed=seed, protocol=protocol, strategy=policy)
        result["phase_costs"]["analysis."+arm] = elapsed(started)
        result["arms"][arm] = {"training": training, "evaluation": evaluation, "checkpoint": checkpoint}
        if content == "joint" and policy == "dynamic":
            started = clock()
            result["inference_controls"][mode] = inference_controls(model, output/arm/"controls", profile,
                                                                    seed=seed, protocol=protocol)
            result["phase_costs"]["controls."+mode] = elapsed(started)
        write(output/"PROGRESS.json", result)
        print(json.dumps({"phase": "trained_evaluated", "arm": arm, "seed": seed, "width": width,
            "ce": evaluation["population_ce_plugin"], "initial_stop_samples": training["initial_stop_samples"],
            "checkpoint": str(output/arm/"MODEL.pt")}), flush=True)
    comparisons = [(f"{mode}.{content}.dynamic", f"{mode}.{content}.fixed")
                   for mode in protocol["modes"] for content in protocol["content_training"]]
    comparisons += [(f"dual.{content}.{policy}", f"ordinary.{content}.{policy}")
                    for content in protocol["content_training"] for policy in protocol["policies"]]
    for left, right in comparisons:
        a, b = result["arms"][left]["evaluation"]["rows"], result["arms"][right]["evaluation"]["rows"]
        if [(r["source"], r["draw"]) for r in a] != [(r["source"], r["draw"]) for r in b]:
            raise ValueError("Source/draw paired evaluation mismatch")
        comparison = paired_ce_difference([r["return"] for r in a], [r["return"] for r in b],
            source_ids=[r["source"] for r in a], bootstrap=protocol["bootstrap_replicates"], seed=seed)
        comparison["amortized_training_deltas"] = {}
        training_cost = {}
        for name in (left, right):
            mode = name.split(".")[0]
            phase = result["phase_costs"]["training."+name]["physical_cost"]
            # Physical training loop cost includes rollout CPU/wall; add only
            # registered service fees, avoiding double billing the same time.
            service = sum(sum(e["service_fee"] for e in json.loads(p.read_text())["events"])
                          for p in (output/name/"training").glob("update-*/draw-*/TRAJECTORY.json"))
            training_cost[name] = phase + service + result["phase_costs"]["pretraining."+mode]["physical_cost"]
        for requests in protocol["amortization_requests"]:
            comparison["amortized_training_deltas"][str(requests)] = comparison["ce_delta"]-(training_cost[left]-training_cost[right])/requests
        comparison["training_cost"] = training_cost
        result["comparisons"][left+"__minus__"+right] = comparison
    result["phase_costs"]["entire_cell"] = elapsed(begun)
    result["outer_cost_includes"] = "batch construction, optimizer, identity checks, archive writes, evaluation, fitting, summaries; includes concurrent child CPU when reaped"
    result["timing_limitation"] = protocol["timing_limitation"]
    write(output/"RESULT.json", result)
    return result


def summarize(root):
    cells = [json.loads(path.read_text()) for path in sorted(Path(root).glob("seed-*-width-*/RESULT.json"))]
    protocol = json.loads(PROTOCOL.read_text())
    expected = set(itertools.product(protocol["seeds"], protocol["widths"]))
    identities = {(c["seed"], c["width"]) for c in cells}
    if identities != expected or len(cells) != len(expected) or any(c["smoke"] for c in cells):
        raise ValueError("Only the full, non-smoke registered matrix may be summarized")
    if len({c["protocol_sha256"] for c in cells}) != 1 or len({c["profile_sha256"] for c in cells}) != 1:
        raise ValueError("Mixed protocol/profile in the purported full matrix")
    key = "dual.joint.dynamic__minus__dual.joint.fixed"
    primary = [{"seed": c["seed"], "width": c["width"], **c["comparisons"][key]} for c in cells]
    robust_positive = all(p["ce_delta"] > 0 and p["ce_delta_percentile_95"][0] > 0 for p in primary)
    result = {"schema": "hepta.generation.v3.complete-development-matrix", "cells": len(cells),
        "seed_widths": sorted([list(x) for x in identities]), "primary_comparison": key,
        "primary_endpoints": primary, "all_registered_endpoint_lower_bounds_positive": robust_positive,
        "research_effect_qualified": False, "confirmation_sources_consumed": 0,
        "interpretation": "Marginal source-bootstrap intervals are development diagnostics, not multiplicity-adjusted confirmatory evidence.",
        "initial_stop_training_samples": sum(a["training"]["initial_stop_samples"] for c in cells for a in c["arms"].values()),
        "training_trajectories": sum(a["training"]["actual_episodes"] for c in cells for a in c["arms"].values()),
        "analysis_trajectories": sum(len(a["evaluation"]["rows"]) for c in cells for a in c["arms"].values()),
        "inference_control_trajectories": sum(len(a["rows"]) for c in cells for mode in c["inference_controls"].values() for a in mode.values()),
        "failures": sum(a["training"]["failures"]+a["evaluation"]["failures"] for c in cells for a in c["arms"].values()),
        "outer_phase_cost": {"wall_seconds": sum(c["phase_costs"]["entire_cell"]["wall_seconds"] for c in cells),
                             "cpu_seconds": sum(c["phase_costs"]["entire_cell"]["cpu_seconds"] for c in cells)}}
    write(Path(root)/"SUMMARY.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=17); parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--smoke", action="store_true"); parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    result = summarize(args.output) if args.summarize else run_cell(args.output, seed=args.seed, width=args.width, smoke=args.smoke)
    print(json.dumps({"completed": True, "cells": result.get("cells"), "seed": result.get("seed"), "width": result.get("width")}), flush=True)


if __name__ == "__main__":
    main()
