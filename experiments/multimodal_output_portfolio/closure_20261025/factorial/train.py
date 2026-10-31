"""Matched base training, recorded before downstream evaluation is opened."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import time

import torch

from ...v7.sources import load_roles
from ...v7.training import TrainConfig, train_profiles


MANIFEST_SHA = "60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True, choices=(29, 43))
    args = parser.parse_args()
    manifest = args.assets / "abc2-runs/source-recovery-001/source-manifest.json"
    if sha(manifest) != MANIFEST_SHA:
        raise ValueError("Source manifest identity differs")
    config = TrainConfig(seed=args.seed, steps=2000, threads=1)
    area = Path(__file__).resolve().parents[2]
    files = [Path(__file__), *(area / "v7").glob("*.py"),
             *(area / "v6").glob("*.py")]
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / "REGISTRATION.json", {
        "schema": "hepta.closure.factorial.base-training.v1",
        "registered_unix_ns": time.time_ns(), "config": asdict(config),
        "factors": {"base_objective": ["supervised", "terminal_entropic_ndu"],
                    "gate_objective": ["mean", "entropic"],
                    "inference": ["committed_plan", "feedback_second_action"]},
        "source_sha256": {str(p.relative_to(area)): sha(p) for p in files},
        "manifest_file_sha256": MANIFEST_SHA, "source_roles_read": ["train"],
        "new_evaluation_sources_opened": False,
        "base_objective_is_emitted_output_utility": False,
        "paired_initialization_batches_noise_and_action_schedule": True,
        "environment": {"torch": torch.__version__, "python": platform.python_version()},
    })
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    corpus = load_roles(args.assets / "abc2-assets/mnist", manifest, roles=("train",))
    with (args.output / "progress.jsonl").open("x") as stream:
        def progress(profile, record):
            row = {"profile": profile, **record}
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            print(json.dumps({"seed": args.seed, **row}), flush=True)
        snapshots, reports = train_profiles(corpus, config, progress=progress)
    for profile, snapshot in snapshots.items():
        path = args.output / (profile + ".pt")
        snapshot.save(path)
        reports[profile]["checkpoint_file_sha256"] = sha(path)
    if (reports["supervised"]["schedule_sha256"] != reports["terminal_entropic_ndu"]["schedule_sha256"]
            or reports["supervised"]["initial_parameter_sha256"] !=
            reports["terminal_entropic_ndu"]["initial_parameter_sha256"]):
        raise ValueError("Matched base training was not paired")
    write(args.output / "RESULTS.json", {
        "schema": "hepta.closure.factorial.base-training-result.v1", "status": "complete",
        "registration_sha256": sha(args.output / "REGISTRATION.json"), "arms": reports,
        "whole_process_wall_ns": time.perf_counter_ns() - wall,
        "whole_process_cpu_ns": time.process_time_ns() - cpu,
    })


if __name__ == "__main__":
    main()
