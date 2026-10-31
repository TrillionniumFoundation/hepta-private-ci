"""Fresh paired trajectories after source and candidate identities are frozen."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time
import traceback

import numpy as np
import torch

from ..round7.policy import Policy, run_episode
from ..round7.task import generate_episode
from .calibration import load_calibrated
from .control_exchange import exchanged_model
from .gaussian_policy import UnboundedGaussianPolicy
from .protocol import EPISODES_PER_FIT_REGIME, MODES, SEEDS, STAGES, WORLD_START, configurations


def verify_manifest(root):
    path = root / "FREEZE.json"
    frozen = json.loads(path.read_text())
    if frozen["confirmation_started"]:
        raise ValueError("expected an immutable pre-confirmation manifest")
    for relative, expected in frozen["files"].items():
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("frozen input changed: " + relative)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def arm_specs():
    specs = {}
    for mode in MODES:
        for stage in STAGES:
            for deployment in ("hard", "mean"):
                specs[f"{mode}/{stage}/{deployment}"] = ("calibrated", mode, stage, deployment)
    specs["task_DP"] = ("oracle", "optimal", None, None)
    specs["myopic_DP"] = ("oracle", "myopic", None, None)
    for mode in ("continuous", "clocked", "first_passage"):
        for deployment in ("hard", "mean"):
            specs[f"brownian_anchor/{mode}/{deployment}"] = ("brownian", mode, None, deployment)
    for operator in ("gaussian", "probit"):
        for deployment in ("hard", "mean"):
            specs[f"unbounded/{operator}/{deployment}"] = ("unbounded", operator, None, deployment)
    return specs


def load_candidates(root, seed):
    models = {}
    for mode in MODES:
        for stage in STAGES:
            path = root / "evidence/calibration_models" / f"{mode}_none_{seed}_{stage}.json"
            models[mode, stage] = load_calibrated(path)[0]
    anchor = models["first_passage", "baseline"]
    brownian = {mode: exchanged_model(anchor, mode, "r8-brownian-images-v1")
                for mode in ("continuous", "clocked", "first_passage")}
    return models, brownian


def make_policy(spec, models, brownian, latent_seed):
    kind, mode, stage, deployment = spec
    if kind == "oracle":
        return Policy(oracle_kind=mode)
    if kind == "calibrated":
        return Policy(models[mode, stage], head=1, deployment=deployment, seed=latent_seed)
    if kind == "brownian":
        return Policy(brownian[mode], head=1, deployment=deployment, seed=latent_seed)
    if kind == "unbounded":
        return UnboundedGaussianPolicy(brownian["continuous"], seed=latent_seed,
                                       deployment=deployment, operator=mode, order=48)
    raise ValueError(kind)


def run(root, output):
    torch.set_num_threads(1)
    root, output = Path(root), Path(output)
    freeze_sha = verify_manifest(root)
    output.mkdir(parents=True, exist_ok=False)
    specs, failures, count = arm_specs(), [], 0
    started, cpu_started = time.perf_counter(), time.process_time()
    sums = {}
    with gzip.open(output / "trajectories.jsonl.gz", "wt", encoding="utf8", compresslevel=6) as raw:
        for fit_index, seed in enumerate(SEEDS):
            models, brownian = load_candidates(root, seed)
            for regime_index, regime in enumerate(WORLD_START):
                presets = configurations(regime)
                for index in range(EPISODES_PER_FIT_REGIME):
                    world_seed = WORLD_START[regime] + fit_index * 10000 + index
                    latent_seed = 930000000 + regime_index * 1000000 + fit_index * 10000 + index
                    parameters = presets[index % len(presets)]
                    episode = generate_episode(world_seed, parameters)
                    arm_order = np.random.default_rng(world_seed + 1000000000).permutation(list(specs))
                    for arm in arm_order:
                        identity = {"arm": str(arm), "fit_seed": seed, "regime": regime,
                                    "configuration_index": index % len(presets), "world_seed": world_seed,
                                    "latent_seed": latent_seed, "freeze_sha256": freeze_sha}
                        try:
                            policy = make_policy(specs[arm], models, brownian, latent_seed)
                            result = run_episode(policy, episode)
                            record = dict(identity, status="complete", **result)
                            key = (regime, str(arm), seed)
                            aggregate = sums.setdefault(key, {"count": 0})
                            aggregate["count"] += 1
                            for field in ("registered_return", "task_return", "quality", "event_count", "decisions",
                                          "prediction_ns", "process_cpu_ns", "kernel_ns", "wire_bytes", "guard_fallbacks"):
                                aggregate[field] = aggregate.get(field, 0.0) + result[field]
                        except Exception as error:
                            record = dict(identity, status="failed", error=repr(error), traceback=traceback.format_exc())
                            failures.append(record)
                        raw.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                        count += 1
                    if (index + 1) % 32 == 0:
                        print(json.dumps({"fit_seed": seed, "regime": regime, "worlds": index + 1,
                                          "attempts": count, "failures": len(failures)}), flush=True)
    rows = [dict(regime=regime, arm=arm, fit_seed=seed, **values)
            for (regime, arm, seed), values in sorted(sums.items())]
    if verify_manifest(root) != freeze_sha:
        raise AssertionError("frozen inputs changed during confirmation")
    result = {"schema": "hepta.contract-closure.confirmation.v1", "freeze_sha256": freeze_sha,
              "attempts": count, "expected_attempts": len(SEEDS) * len(WORLD_START) * EPISODES_PER_FIT_REGIME * len(specs),
              "arm_count": len(specs), "failures": failures, "fit_arm_sums": rows,
              "wall_seconds": time.perf_counter() - started,
              "controller_process_cpu_seconds": time.process_time() - cpu_started,
              "environment": {"python": platform.python_version(), "numpy": np.__version__,
                              "torch": torch.__version__, "torch_threads": torch.get_num_threads()},
              "execution": "Original public-state task step; physical artifact IO and native owner audited separately",
              "sampling": "Gaussian/probit endpoints are equivalent paired controls, not independent models"}
    (output / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if failures or count != result["expected_attempts"]:
        raise RuntimeError("confirmation has failures or missing attempts; raw records retained")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).parent))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.root, args.output)
