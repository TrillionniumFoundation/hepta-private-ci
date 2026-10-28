"""Matched mean/risk full-path training with real emitted artifact rewards."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import shutil
import time

import numpy as np
import torch

from ..v6.data import make_batch
from ..v6.neural import parameter_hash
from ..v6.plan_training import ControlledSnapshot
from ..continuation_20261027.joint.run import reference_observer
from .generator import (STAGES, actual_outputs, emit, file_sha, final_state, hashes,
                        leave_one_out, load_model, repeat_state, save_model, set_stage)
from .fullpath_evaluate import evaluate, identities, repeated_target, select
from .fullpath_protocol import P, allocate, profiles, write_json
from .profile import moment_cost


def fit(reference, corpus, observer, profile, primary, seed, arm, directory, steps_per_stage=None):
    steps_per_stage = P["steps_per_stage"] if steps_per_stage is None else steps_per_stage
    directory.mkdir(parents=True, exist_ok=False)
    model = deepcopy(reference._base._model).train()
    before = hashes(model)
    frozen = (parameter_hash(reference._base._model), parameter_hash(reference._gate), parameter_hash(observer))
    rng = torch.Generator().manual_seed(seed * 1171 + 281503)
    schedule, delivered = hashlib.sha256(), hashlib.sha256()
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    history, checkpoints, stage_records, cost_trace = [], [], [], []
    codec_totals = {"codec_observer_wall_ns": 0, "codec_observer_cpu_ns": 0,
                    "actual_bundles": 0, "files_written_and_reopened": 0}
    n, k = P["batch_size"], P["emissions_per_context"]
    for stage_index, (stage, _) in enumerate(STAGES):
        enabled = set_stage(model, stage_index)
        optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=P["learning_rate"])
        gradients = {name: 0. for name in enabled}
        stage_before = hashes(model)
        for local_step in range(steps_per_stage):
            step = stage_index * steps_per_stage + local_step
            condition = P["conditions"][step % len(P["conditions"])]
            batch_seed = seed * 1000003 + step * 31 + 2810463
            batch = make_batch(corpus, "train", n, batch_seed, corruption=condition)
            noise = torch.randn(n, model.hidden, generator=rng)
            schedule.update(str(batch_seed).encode())
            schedule.update(noise.numpy().tobytes())
            schedule.update(rng.get_state().numpy().tobytes())
            state, _ = final_state(model, reference, batch.observation, noise)
            sample = emit(model, repeat_state(state, k), rng)
            returns, rows, measured = actual_outputs(sample, repeated_target(batch.target, k), observer,
                profile, directory / f"temporary-step-{step}", identities(batch, condition, 0, k, seed))
            for key, value in measured.items():
                codec_totals[key] += value
            for row in rows:
                delivered.update(json.dumps(row["artifact_sha256"], sort_keys=True).encode())
            costs = torch.tensor([moment_cost(float(v), profile.gamma) for v in returns], dtype=torch.float64).reshape(k, n)
            advantages = leave_one_out(costs).detach()
            objective = (advantages * sample.log_prob.reshape(k, n)).mean()
            optimizer.zero_grad(set_to_none=True)
            objective.backward()
            for name in enabled:
                squared = sum(float(p.grad.detach().double().square().sum())
                              for p in getattr(model, name).parameters() if p.grad is not None)
                gradients[name] += squared ** .5
            norm = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], P["gradient_clip"])
            if not torch.isfinite(norm):
                raise FloatingPointError("Nonfinite actual-emission score gradient")
            optimizer.step()
            history.append({"step": step + 1, "stage": stage, "condition": condition,
                            "mean_net": float(returns.mean()), "moment_cost": float(costs.mean()),
                            "gradient_norm_before_clip": float(norm),
                            "profile_sha256": profile.digest})
            cost_trace.append(costs.numpy())
            if (local_step + 1) % 20 == 0:
                print(f"fullpath seed={seed} arm={arm} stage={stage} step={local_step + 1} net={float(returns.mean()):.5f}", flush=True)
        path = directory / f"{stage}.pt"
        save_model(model, path, profile, {"seed": seed, "arm": arm, "stage": stage,
                                        "base_checkpoint_sha256": P["reference_checkpoint_sha256"]})
        reloaded, _ = load_model(path, profile)
        if parameter_hash(reloaded) != parameter_hash(model):
            raise RuntimeError("Checkpoint changed on reload")
        checkpoints.append((stage, path))
        after = hashes(model)
        stage_records.append({"stage": stage, "enabled_modules": enabled,
            "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
            "actual_output_gradient_norm_sum": gradients,
            "changed_modules": {name: stage_before[name] != after[name] for name in after},
            "checkpoint_sha256": file_sha(path)})
    if frozen != (parameter_hash(reference._base._model), parameter_hash(reference._gate), parameter_hash(observer)):
        raise RuntimeError("A frozen reference or reward observer changed")
    np.savez_compressed(directory / "actual_cost_trace.npz", costs=np.stack(cost_trace))
    total_steps = len(STAGES) * steps_per_stage
    record = {"arm": arm, "seed": seed, "profile_sha256": profile.digest,
        "schedule_sha256": schedule.hexdigest(), "actual_output_stream_sha256": delivered.hexdigest(),
        "before_modules": before, "after_modules": hashes(model), "stages": stage_records,
        "history": history, "training_counts": {"optimizer_steps": total_steps,
            "current_encoder_examples": total_steps * n, "frozen_reference_encoder_examples": total_steps * n,
            "gate_examples": total_steps * n, "current_transition_examples": total_steps * n * 2,
            "pixel_emissions": total_steps * n * k, "token_emissions": total_steps * n * k * 7,
            "actual_bundle_roundtrips": total_steps * n * k, "observer_digit_examples": total_steps * n * k * 2},
        "codec_totals": codec_totals, "wall_ns": time.perf_counter_ns() - wall,
        "cpu_ns": time.process_time_ns() - cpu, "reward_gradient_before_clipping": "unbiased conditional likelihood-ratio with independent leave-one-out baseline",
        "optimizer_is_unbiased_or_globally_optimal": False, "auxiliary_reward_proxy": False,
        "native_continuation_trained": False, "training_media": "actual files reopened then removed; per-step cost trace, ordered digest, RNG schedule and exact code retained"}
    write_json(directory / "TRAINING.json", record)
    selection = select(checkpoints, reference, corpus, observer, profile, primary, seed, directory / "validation")
    return record, selection


def development(assets, baseline, output, smoke=False):
    if file_sha(baseline) != P["reference_checkpoint_sha256"]:
        raise ValueError("Not the pinned prior selected strong baseline")
    output.mkdir(parents=True, exist_ok=False)
    primary, mean, semantics = profiles(assets / "ndu-runs/full-002/reward-observer.pt")
    write_json(output / "PROTOCOL.json", {**P, "smoke_only": smoke})
    write_json(output / "PROFILE.json", primary.to_dict())
    write_json(output / "MEAN_CONTROL_PROFILE.json", mean.to_dict())
    write_json(output / "SEMANTICS.json", semantics)
    if smoke:
        from ..continuation_20261027.joint.data import historical_corpus
        corpus = historical_corpus(assets)
    else:
        corpus = allocate(assets, output / "SOURCE_ALLOCATION.json")
    source = Path(__file__).parent
    source_files = ["generator.py", "fullpath_protocol.py", "fullpath_train.py", "fullpath_evaluate.py", "profile.py"]
    (output / "executed-source").mkdir()
    for name in source_files:
        shutil.copyfile(source / name, output / "executed-source" / name)
    write_json(output / "RUNTIME.json", {"python": platform.python_version(), "torch": torch.__version__,
        "threads": P["threads"], "cuda": torch.cuda.is_available(),
        "baseline_sha256": file_sha(baseline), "executed_source_sha256": {n: file_sha(source / n) for n in source_files},
        "audit_observer_loaded": False, "qualification_predictions": 0})
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    reference = ControlledSnapshot.load(baseline)
    observer = reference_observer(assets, "reward")
    selections = []
    for seed in ([17] if smoke else P["training_seeds"]):
        matched = []
        for arm, profile in (("fullpath_mean", mean), ("fullpath_risk", primary)):
            record, selection = fit(reference, corpus, observer, profile, primary, seed, arm,
                                    output / f"seed-{seed}-{arm}", steps_per_stage=1 if smoke else None)
            selections.append({"arm": arm, **selection})
            matched.append(record)
            write_json(output / "SELECTIONS.json", selections)
        for field in ("schedule_sha256", "training_counts", "before_modules"):
            if matched[0][field] != matched[1][field]:
                raise ValueError(f"Matched budget/randomness differ: {field}")
    write_json(output / "DEVELOPMENT_SEAL.json", {"profile_sha256": primary.digest,
        "protocol_sha256": file_sha(output / "PROTOCOL.json"),
        "selection_sha256": file_sha(output / "SELECTIONS.json"),
        "source_allocation_sha256": None if smoke else file_sha(output / "SOURCE_ALLOCATION.json"),
        "smoke_only": smoke, "qualification_predictions": 0})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "baseline", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    development(args.assets, args.baseline, args.output, args.smoke)
