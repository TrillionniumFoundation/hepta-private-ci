"""Separate first-step cost replay; no candidate or evaluation changes.

The external monitor used namespace PIDs with a host-mounted /proc and its
VmRSS/VmHWM observations are invalid. This replay reads SELF usage inside the
actual Torch process. Full launch child-RUSAGE CPU/RSS records remain valid.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import time

import torch

from ...round7.data import task_configuration
from ...round7.joint_control import build_graph
from .full_joint import HERE, evaluate, load_joint, settings, sha, verify_registration, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    evidence = HERE / "evidence/full_joint_v1"
    verify_registration(evidence / "REGISTRATION.json")
    candidate_digest = sha(evidence / "CANDIDATES.json")
    source = evidence / "cases/first_passage_11/initial.json"
    initial_digest = sha(source)
    model, _ = load_joint(source)
    graph = build_graph([task_configuration(i) for i in range(8)])
    config = settings()["training"]
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam(parameters, lr=config["learning_rate"], betas=tuple(config["betas"]),
                                 eps=config["epsilon"], weight_decay=config["weight_decay"])
    before = resource.getrusage(resource.RUSAGE_SELF)
    cpu, wall = time.process_time(), time.perf_counter()
    optimizer.zero_grad(set_to_none=True)
    metrics, _ = evaluate(model, graph)
    (-metrics[0]).backward()
    norm = torch.nn.utils.clip_grad_norm_(parameters, config["clip_norm"], error_if_nonfinite=True)
    optimizer.step()
    seconds, cpu_seconds = time.perf_counter()-wall, time.process_time()-cpu
    after = resource.getrusage(resource.RUSAGE_SELF)
    with torch.no_grad():
        next_metrics = evaluate(model, graph)[0].tolist()
    curves = [json.loads(line) for line in (source.parent / "curve.jsonl").read_text().splitlines()]
    actual_pid = os.getpid()
    proc_pid = None
    for row in Path("/proc/self/status").read_text().splitlines():
        if row.startswith("Pid:"):
            proc_pid = int(row.split()[1])
    unchanged = candidate_digest == sha(evidence / "CANDIDATES.json") and initial_digest == sha(source)
    verify_registration(evidence / "REGISTRATION.json")
    write(args.output, {"schema": "hepta.full-joint.first-step-resource-replay.v1",
        "postfreeze_diagnostic": True, "candidate_update_count_unchanged": True,
        "source_sha256": sha(__file__), "registration_sha256": sha(evidence / "REGISTRATION.json"),
        "candidate_manifest_sha256": candidate_digest, "initial_checkpoint_sha256": initial_digest,
        "frozen_inputs_unchanged": unchanged, "mode": "first_passage", "fit_seed": 11,
        "public_states": len(graph.states), "n_grid": model.n_grid, "replayed_updates": 1,
        "replay_wall_seconds": seconds, "replay_process_cpu_seconds": cpu_seconds,
        "process_peak_rss_kib_before_step": before.ru_maxrss,
        "process_peak_rss_kib_through_step": after.ru_maxrss,
        "pre_update_utility": float(metrics[0].detach()), "post_update_metrics": next_metrics,
        "original_training_first_step_wall_seconds": curves[0]["step_wall_seconds"],
        "post_update_utility_difference_from_original_curve": next_metrics[0]-curves[1]["exact_soft_utility"],
        "unclipped_gradient_norm": float(norm), "pid_view": {"os_getpid": actual_pid, "proc_self_pid": proc_pid},
        "discarded_measurements": "All process_memory_observed_after_step0_notification VmRSS/VmHWM values in launch_*.json: namespace PIDs were looked up in a host-mounted /proc. They do not describe the Torch child. Preserve raw observations but never use them as model-memory evidence.",
        "retained_measurements": "Training.json SELF peak RSS and launch child-RUSAGE peak RSS/CPU are namespace-safe. Peak RSS includes interpreter/startup and is not a per-step allocation delta.",
        "scope": "Independent replay of the original initial model solely to measure a full 738-state first update. The in-memory replay object is discarded, no heldout is constructed or read, and no candidate receives a 31st update."})
    print(json.dumps({"public_states": len(graph.states), "wall_seconds": seconds,
                      "peak_rss_kib_through_step": after.ru_maxrss,
                      "original_update_match_error": next_metrics[0]-curves[1]["exact_soft_utility"]}))


if __name__ == "__main__":
    main()
