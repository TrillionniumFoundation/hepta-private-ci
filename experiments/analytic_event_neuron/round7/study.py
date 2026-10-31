"""Frozen, paired whole-trajectory confirmation with complete outcome records."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import resource
import time
import traceback

import numpy as np
import torch

from .data import task_configuration
from .model import load_model
from .policy import Policy, run_episode
from .task import generate_episode


PRIMARY = {
    "A": ("clocked", "none", 0, "hard"),
    "B": ("clocked", "none", 1, "hard"),
    "C": ("first_passage", "none", 0, "hard"),
    "D": ("first_passage", "none", 1, "hard"),
}
SECONDARY = {
    **{name + "_mean": (mode, freeze, head, "mean")
       for name, (mode, freeze, head, _) in PRIMARY.items()},
    "continuous": ("continuous", "none", 1, "mean"),
    "continuous_hard": ("continuous", "none", 1, "hard"),
    "direct_Q": ("direct", "none", 1, "mean"),
    "direct_Q1": ("direct", "none", 0, "mean"),
    "temperature": ("first_passage_temperature", "none", 1, "hard"),
    "B_soft": ("clocked", "none", 1, "hard_soft"),
    "D_soft": ("first_passage", "none", 1, "hard_soft"),
    "B_q24": ("clocked", "none", 1, "q24"),
    "D_q24": ("first_passage", "none", 1, "q24"),
    **{"freeze_" + group: ("first_passage", group, 1, "hard")
       for group in ("content", "dynamics", "noise", "boundary", "reset", "recovery")},
    "clocked_freeze_boundary": ("clocked", "boundary", 1, "hard"),
}
STRESS_ARMS = ("A", "B", "C", "D", "D_mean", "D_soft", "D_q24",
               "continuous", "direct_Q", "temperature", "task_DP")


def checkpoint_path(root, mode, ablation, seed):
    # Explicit registration prevents retained rejected attempts from ever
    # becoming eligible through directory glob order or file synchronization.
    if seed not in range(11, 16):
        raise ValueError("unregistered fit seed")
    if ablation == "none" and mode in ("clocked", "first_passage", "continuous", "direct"):
        folder = "fits_primary"
    elif ablation == "none" and mode == "first_passage_temperature":
        folder = "fits_temperature_corrected"
    elif mode == "first_passage" and ablation in ("content", "dynamics", "noise"):
        folder = "fits_freezes_a"
    elif mode == "first_passage" and ablation in ("boundary", "reset", "recovery"):
        folder = "fits_freezes_b"
    elif mode == "clocked" and ablation == "boundary":
        folder = "fits_clocked_control"
    else:
        raise ValueError("unregistered model/ablation")
    path = Path(root) / folder / f"{mode}_{ablation}_{seed}.json"
    if not path.is_file():
        raise ValueError(f"missing registered checkpoint: {path}")
    return path


def verify_freeze(root):
    root = Path(root)
    manifest_path = root / "FROZEN_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    protocol = json.loads((root / "PROTOCOL.json").read_text())
    if not protocol["frozen"] or manifest.get("confirmation_started", False):
        raise ValueError("a pre-confirmation frozen protocol is required")
    for path, expected in manifest["files"].items():
        actual = hashlib.sha256((root / path).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("frozen bytes changed: " + path)
    return {"sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "manifest": manifest, "protocol": protocol}


def run_confirmation(root, output, *, allow_development=False, count=512, stress_count=256):
    root, output = Path(root), Path(output)
    if output.exists():
        raise FileExistsError("retain prior runs; output directory must be new")
    freeze = {"sha256": None} if allow_development else verify_freeze(root)
    if not allow_development and (count != 512 or stress_count != 256):
        raise ValueError("registered sample size cannot be changed at confirmation")
    output.mkdir(parents=True)
    started, cpu_started = time.perf_counter(), time.process_time()
    records_path = output / "trajectories.jsonl.gz"
    failures, total, arm_counts = [], 0, {}
    regimes = (("nominal", count, 2000000), ("drift", stress_count, 3000000),
               ("missing", stress_count, 4000000), ("cost_shift", stress_count, 6000000))
    if allow_development:
        regimes = (("development_only", count, 210000),)
    seeds = [11] if allow_development else list(range(11, 16))
    try:
        with gzip.open(records_path, "wt", encoding="utf8", compresslevel=6) as stream:
            for fit_index, fit_seed in enumerate(seeds):
                models = {}
                specs = {**PRIMARY, **SECONDARY}
                if allow_development:
                    specs = {name: spec for name, spec in PRIMARY.items()}
                for name, (mode, ablation, _, _) in specs.items():
                    key = mode, ablation
                    if key not in models:
                        path = checkpoint_path(root / "evidence", mode, ablation, fit_seed)
                        models[key] = load_model(path)[0]
                for regime_index, (regime, size, base) in enumerate(regimes):
                    arms = list(specs) + ["task_DP", "myopic_DP"]
                    if regime not in ("nominal", "development_only"):
                        arms = list(STRESS_ARMS)
                    for index in range(size):
                        episode_seed = base + fit_index * 10000 + index
                        parameters = task_configuration(index, "nominal" if allow_development else regime)
                        episode = generate_episode(episode_seed, parameters)
                        latent_seed = 920000000 + regime_index * 1000000 + fit_index * 10000 + index
                        if allow_development:
                            latent_seed = 880000000 + index
                        order = np.random.default_rng(700000000 + latent_seed).permutation(arms)
                        for name in order:
                            if name in ("task_DP", "myopic_DP"):
                                policy = Policy(oracle_kind="optimal" if name == "task_DP" else "myopic")
                            else:
                                mode, ablation, head, deployment = specs[name]
                                policy = Policy(models[mode, ablation], head=head, deployment=deployment,
                                                seed=latent_seed)
                            identity = {"arm": str(name), "fit_seed": fit_seed, "regime": regime,
                                        "episode_index": index, "episode_seed": episode_seed,
                                        "latent_seed": latent_seed}
                            try:
                                record = {**identity, "status": "complete", **run_episode(policy, episode)}
                                encoded = json.dumps(record, sort_keys=True, allow_nan=False,
                                                     separators=(",", ":"))
                            except Exception:
                                record = {**identity, "status": "failed", "traceback": traceback.format_exc()}
                                failures.append(record)
                                encoded = json.dumps(record, sort_keys=True)
                            stream.write(encoded + "\n")
                            total += 1
                            key = regime + "/" + str(name)
                            arm_counts[key] = arm_counts.get(key, 0) + 1
                    stream.flush()
                    print(json.dumps({"fit_seed": fit_seed, "regime": regime,
                                      "trajectories_so_far": total, "failures": len(failures)}), flush=True)
    except Exception:
        failures.append({"status": "run_aborted", "traceback": traceback.format_exc(),
                         "completed_record_count": total})
    receipt = {"status": "complete" if not failures else "incomplete",
               "frozen_manifest_sha256": freeze["sha256"], "development_only": allow_development,
               "trajectories": total, "failures": failures, "arm_counts": arm_counts,
               "wall_seconds": time.perf_counter() - started,
               "process_cpu_seconds": time.process_time() - cpu_started,
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "python": platform.python_version(), "platform": platform.platform(),
               "torch": torch.__version__, "numpy": np.__version__, "torch_threads": torch.get_num_threads(),
               "records_sha256": hashlib.sha256(records_path.read_bytes()).hexdigest() if records_path.exists() else None,
               "records_bytes": records_path.stat().st_size if records_path.exists() else 0,
               "oracle_scope": "task_DP is exact for task_return only, not a bound on registered_return"}
    (output / "RUN_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).parent))
    parser.add_argument("--output", required=True)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--count", type=int, default=512)
    parser.add_argument("--stress-count", type=int, default=256)
    args = parser.parse_args()
    torch.set_num_threads(1)
    result = run_confirmation(args.root, args.output, allow_development=args.development,
                              count=args.count, stress_count=args.stress_count)
    print(json.dumps({key: result[key] for key in ("status", "trajectories", "wall_seconds")}), flush=True)


if __name__ == "__main__":
    main()
