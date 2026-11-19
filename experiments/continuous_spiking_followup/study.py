"""Frozen inventory for compute-matched training and actual streaming control."""

import argparse
import hashlib
import json
from pathlib import Path
import time


BASE_COMMIT = "23c98e77e4d2cc98e8c32caf7db763bc85c6794b"
NATIVE_COMMIT = "7bec42aa4f79432f4a724d5295c67f9d69ee5a8d"
ARCHITECTURES = [
    "hcsn",
    "lif_snn",
    "continuous_rnn",
    "two_gates",
    "cfc",
    "mamba1",
    "transformer",
]
COMMON = {
    "learning_rates": [0.001, 0.003],
    "candidate_cpu_seconds": 12.0,
    "cpu_milestone_fractions": [0.25, 0.5, 1.0],
    "max_updates": 4096,
    "batch_size": 32,
    "data_seed": 8123,
    "val_size": 256,
    "test_size": 512,
    "train_size": 2048,
    "width": 32,
    "depth": 1,
    "length": 32,
}
SCALE_CONFIGS = [
    ("center", "long_memory", 32, 1, 1024, 32),
    ("capacity", "long_memory", 16, 1, 1024, 32),
    ("capacity", "long_memory", 64, 2, 1024, 32),
    ("capacity", "long_memory", 128, 2, 1024, 32),
    ("data", "long_memory", 32, 1, 256, 32),
    ("data", "long_memory", 32, 1, 4096, 32),
    ("context", "long_memory", 32, 1, 1024, 64),
    ("context", "long_memory", 32, 1, 1024, 128),
    ("joint", "multimodal_select", 64, 2, 4096, 128),
]


def inventory():
    jobs = []
    for task in ("synthetic", "multimodal_select"):
        for arch in ("hcsn", "single", "no_adaptation", "ordinary", "continuous_rnn"):
            for seed in range(5101, 5106):
                jobs.append(
                    {
                        **COMMON,
                        "stage": "mechanism",
                        "task": task,
                        "architecture": arch,
                        "seed": seed,
                        "match_cell_budget": arch == "continuous_rnn",
                        "id": f"mechanism/{task}/{arch}/seed{seed}",
                    }
                )
    for task in ("mnist", "fsdd", "multimodal_select", "long_memory"):
        for arch in ARCHITECTURES:
            for seed in range(6201, 6204):
                jobs.append(
                    {
                        **COMMON,
                        "stage": "representation",
                        "task": task,
                        "architecture": arch,
                        "seed": seed,
                        "match_cell_budget": False,
                        "id": f"representation/{task}/{arch}/seed{seed}",
                    }
                )
    for number, (axis, task, width, depth, size, length) in enumerate(SCALE_CONFIGS):
        for arch in ("hcsn", "mamba1", "transformer"):
            for seed in range(7301, 7304):
                jobs.append(
                    {
                        **COMMON,
                        "stage": "scaling",
                        "task": task,
                        "architecture": arch,
                        "seed": seed,
                        "axis": axis,
                        "width": width,
                        "depth": depth,
                        "train_size": size,
                        "length": length,
                        "match_cell_budget": False,
                        "configuration": number,
                        "id": f"scaling/config{number:02d}/{arch}/seed{seed}",
                    }
                )
    return jobs


def protocol(jobs):
    encoded = json.dumps(jobs, sort_keys=True).encode()
    return {
        "version": "hcsn-compute-stream-v2",
        "base_commit": BASE_COMMIT,
        "base_source_seal": "bb0d2eda33c34785da9563a84a06ed4c5d2391826e52173452ee43924723de02",
        "native_contract_commit": NATIVE_COMMIT,
        "native_binary_sha256": "1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5",
        "native_reference_sha256": "06c3d049f87505ef8a4abe9acd2dccc9ca0d8b4febb927de089475fc0954274f",
        "runs_sha256": hashlib.sha256(encoded).hexdigest(),
        "jobs": {"mechanism": 50, "representation": 84, "scaling": 81},
        "common": COMMON,
        "primary": {
            "mechanism": "HCSN minus each of four paired controls; accuracy; five seeds; per-task 98.75% Student-t CI",
            "practical_effect_reference": 0.01,
            "representation_scaling": "descriptive mean and sample SD across three optimization seeds",
            "selection": "validation CE only across both learning rates and three CPU milestones; fixed candidate-order ties",
            "budget": "12 process-CPU training seconds for each LR; all search overhead charged separately; final step overshoot retained",
        },
        "boundary": {
            "actor_seeds": [4401, 4402, 4403, 4404, 4405],
            "actor_source": "unchanged study001 selected actor checkpoints; no new actor-training cost attributed to zero",
            "new_episode_seed_offset": 100000,
            "train_size": 1024,
            "validation_size": 256,
            "test_id_size": 64,
            "test_ood_size": 64,
            "train_snr": [0.25, 0.5, 0.8],
            "train_cost": [0.005, 0.025, 0.08],
            "train_horizon": 16,
            "ood_snr": [0.15, 0.35, 0.7, 1.1],
            "ood_cost": [0.01, 0.04, 0.12],
            "ood_horizon": 24,
            "direct_updates": 100,
            "calibration": "one positive temperature fit on training prefixes; all three primary policies share calibrated odds",
            "policies": ["fixed", "direct", "value"],
            "comparison": "same actor, calibrated odds, SNR/cost/horizon, correctness reward and every paid observation; causal stop",
            "utility_intervals": "four value-minus-fixed/direct contrasts across ID/OOD; 98.75% paired Student-t intervals",
            "cold_replay": "first Python episode per split/policy is replayed from serialized state in-process; first continuing native episode per split/policy restores stream, task cursor and native owner in a new native process",
            "native": {
                "actor_seed": 4403,
                "episodes_per_split_policy": 16,
                "total_policy_episodes": 96,
                "action_authority": "original sparse kernel and native NDU",
            },
        },
        "stream_measurement": {
            "selection": "all representation seed6201 and scaling seed7301 winners, independent of score",
            "cases": 55,
            "batch_size": 16,
            "warmups": 2,
            "repeats": 7,
            "sequence_parity_rtol": 3e-5,
            "sequence_parity_atol": 3e-6,
            "separate_process_replay": "seven MNIST representation winners at seed6201",
            "scope": "full-sequence versus genuine incremental forward; reset and restoration costs separate; persistent state bytes not RSS",
        },
        "limits": [
            "Fresh episode seed does not create a new raw MNIST/FSDD source population.",
            "Equal process CPU does not imply equal updates, parameter count, energy or optimized GPU cost.",
            "CPU-budget update counts depend on machine/runtime; input streams and retained checkpoints remain reproducible.",
            "The natural cell threshold remains learned; task Bellman stopping is a separate value boundary.",
            "Neural score calibration does not prove Bayesian Markov transition correctness.",
            "Long-memory grows genuine distractors; joint multimodal length remains null-step stress.",
            "Original native value-to-action adapter is not evidence of learned sparse-head superiority.",
        ],
    }


def freeze(package):
    package = Path(package)
    if any((package / "results" / "study002").rglob("START.json")):
        raise FileExistsError(
            "a started study cannot be resealed; preserve it and create a new study"
        )
    jobs = inventory()
    for name, value in (("RUNS.json", jobs), ("PROTOCOL.json", protocol(jobs))):
        (package / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    files = {}
    for path in sorted(package.rglob("*")):
        rel = path.relative_to(package)
        if "results" in rel.parts or "__pycache__" in rel.parts:
            continue
        if path.is_file() and (
            path.suffix == ".py" or path.name in {"PROTOCOL.json", "requirements.txt"}
        ):
            files[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    (package / "SOURCE_SEAL.json").write_text(
        json.dumps(
            {
                "files": files,
                "sha256": digest,
                "created_unix": time.time(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return {"training_jobs": len(jobs), "source_seal": digest}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            freeze(Path(__file__).parent) if args.freeze else protocol(inventory())
        )
    )
