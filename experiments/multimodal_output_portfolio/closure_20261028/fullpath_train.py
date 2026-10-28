"""Matched true-artifact NDU training with conditional baselines and LAX."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import shutil
import time
from types import SimpleNamespace

import numpy as np
import torch

from ..v6.data import make_batch
from ..v6.neural import parameter_hash
from ..v6.plan_training import ControlledSnapshot
from ..continuation_20261027.joint.run import reference_observer
from .fullpath_evaluate import identities, repeated_target, select
from .fullpath_lax import continuous_proxy, loss_from_return, surrogate
from .fullpath_model import (STAGES, actual_outputs, emit, episode_costs, file_sha, final_state,
                             hashes, load_model, repeat_state, save_model, set_stage, text_emission)
from .fullpath_protocol import P, allocate, profiles, write_json


def fit(reference, corpus, observer, profile, primary, seed, arm, directory, steps_per_stage=None):
    steps_per_stage = P["steps_per_stage"] if steps_per_stage is None else steps_per_stage
    directory.mkdir(parents=True, exist_ok=False)
    model = deepcopy(reference._base._model).train()
    before = hashes(model)
    frozen = (parameter_hash(reference._base._model), parameter_hash(reference._gate), parameter_hash(observer))
    rng = torch.Generator().manual_seed(seed * 1171 + 28261003)
    schedule, delivered = hashlib.sha256(), hashlib.sha256()
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    history, checkpoints, stage_records, cost_trace = [], [], [], []
    codec_totals = {"codec_observer_wall_ns": 0, "codec_observer_cpu_ns": 0,
                    "actual_bundles": 0, "files_written_and_reopened": 0}
    n, k = P["batch_size"], P["emissions_per_context"]
    deployment_cost = sum(event.amount for event in episode_costs(profile, "fixed-work-unit"))
    for stage_index, (stage, _) in enumerate(STAGES):
        enabled = set_stage(model, stage_index)
        optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=P["learning_rate"])
        gradients = {name: 0.0 for name in enabled}
        stage_before = hashes(model)
        for local_step in range(steps_per_stage):
            step = stage_index * steps_per_stage + local_step
            condition = P["conditions"][step % len(P["conditions"])]
            batch_seed = seed * 1000003 + step * 31 + 28261033
            batch = make_batch(corpus, "train", n, batch_seed, corruption=condition)
            noise = torch.randn(n, model.hidden, generator=rng)
            schedule.update(str(batch_seed).encode()); schedule.update(noise.numpy().tobytes())
            schedule.update(rng.get_state().numpy().tobytes())
            state, _ = final_state(model, reference, batch.observation, noise)
            repeated = repeat_state(state, k)
            target = repeated_target(batch.target, k)
            sample = emit(model, repeated, rng)
            with torch.no_grad():
                greedy, _ = text_emission(model, repeated, deterministic=True)
            counterfactuals = {"actual": sample,
                "image_baseline": SimpleNamespace(pixels=sample.image_mean.detach().sigmoid().reshape(-1, 1, 28, 56), tokens=sample.tokens),
                "text_baseline": SimpleNamespace(pixels=sample.pixels, tokens=greedy)}
            losses, rows_by_kind = {}, {}
            for kind, output in counterfactuals.items():
                _, rows, measured = actual_outputs(output, target, observer, profile,
                    directory / f"temporary-{step}-{kind}", identities(batch, condition, 0, k, seed))
                rows_by_kind[kind] = rows
                for key, value in measured.items():
                    codec_totals[key] += value
                actual_returns = torch.tensor([row["net_return"] for row in rows], dtype=torch.float64)
                losses[kind] = loss_from_return(actual_returns, profile.gamma)
                for row in rows:
                    delivered.update(kind.encode())
                    delivered.update(json.dumps(row["artifact_sha256"], sort_keys=True).encode())
            proxy_sample = continuous_proxy(observer, sample.pathwise_pixels(), sample.tokens, target,
                                            profile.gamma, deployment_cost)
            with torch.no_grad():
                proxy_mean = continuous_proxy(observer, sample.image_mean.sigmoid().reshape(-1, 1, 28, 56),
                                              sample.tokens, target, profile.gamma, deployment_cost)
            objective = surrogate(losses["actual"], losses["image_baseline"], losses["text_baseline"],
                                  proxy_sample, proxy_mean, sample.image_log_prob, sample.text_log_prob)
            optimizer.zero_grad(set_to_none=True)
            objective.backward()
            for name in enabled:
                squared = sum(float(parameter.grad.detach().double().square().sum())
                              for parameter in getattr(model, name).parameters() if parameter.grad is not None)
                gradients[name] += squared ** .5
            norm = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], P["gradient_clip"])
            if not torch.isfinite(norm):
                raise FloatingPointError("Nonfinite exact-objective LAX gradient")
            optimizer.step()
            values = [row["net_return"] for row in rows_by_kind["actual"]]
            history.append({"step": step + 1, "stage": stage, "condition": condition,
                            "mean_actual_net_return": float(np.mean(values)),
                            "mean_actual_moment_cost": float(losses["actual"].mean()),
                            "gradient_norm_before_clip": float(norm), "profile_sha256": profile.digest})
            cost_trace.append(losses["actual"].detach().numpy().reshape(k, n))
            if (local_step + 1) % 64 == 0 or local_step + 1 == steps_per_stage:
                print(json.dumps({"seed": seed, "arm": arm, "stage": stage, "step": local_step + 1,
                                  "mean_actual_net": float(np.mean(values)), "gradient_norm": float(norm)}), flush=True)
        path = directory / f"{stage}.pt"
        save_model(model, path, profile, {"seed": seed, "arm": arm, "stage": stage,
                                         "base_checkpoint_sha256": P["reference_checkpoint_sha256"]})
        reloaded, _ = load_model(path, profile)
        if parameter_hash(reloaded) != parameter_hash(model):
            raise ValueError("Saved stochastic law changed on deployment reload")
        checkpoints.append((stage, path))
        after = hashes(model)
        stage_records.append({"stage": stage, "enabled_modules": enabled,
                              "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
                              "actual_objective_gradient_norm_sum": gradients,
                              "changed_modules": {name: stage_before[name] != after[name] for name in after},
                              "checkpoint_sha256": file_sha(path)})
    if frozen != (parameter_hash(reference._base._model), parameter_hash(reference._gate), parameter_hash(observer)):
        raise ValueError("A frozen reference or reward observer was modified")
    np.savez_compressed(directory / "actual_moment_trace.npz", costs=np.stack(cost_trace))
    steps = len(STAGES) * steps_per_stage
    record = {"arm": arm, "seed": seed, "profile_sha256": profile.digest,
              "schedule_sha256": schedule.hexdigest(), "actual_output_stream_sha256": delivered.hexdigest(),
              "before_modules": before, "after_modules": hashes(model), "stages": stage_records, "history": history,
              "training_counts": {"optimizer_steps": steps, "current_encoder_examples": steps * n,
                  "frozen_reference_encoder_examples": steps * n, "frozen_gate_examples": steps * n,
                  "current_transition_examples": steps * n * 2, "primary_joint_emissions": steps * n * k,
                  "greedy_text_baseline_emissions": steps * n * k,
                  "actual_primary_bundle_roundtrips": steps * n * k,
                  "actual_control_variate_bundle_roundtrips": steps * n * k * 2,
                  "proxy_digit_forward_examples": steps * n * k * 4},
              "codec_totals": codec_totals, "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "pre_optimizer_gradient": "conditional LR baselines plus zero-mean continuous LAX correction",
              "proxy_replaces_actual_objective": False, "auxiliary_regularizer": False,
              "CPU_parameter_derivative_estimated": False, "complete_physical_cost_certificate": False,
              "training_media": "all actual/counterfactual PNG and UTF8 files reopened before removal; identities, schedule, traces and code archived"}
    write_json(directory / "TRAINING.json", record)
    selection = select(checkpoints, reference, corpus, observer, profile, primary, seed, directory / "validation")
    return record, selection


def development(assets, baseline, output, oracle, smoke=False):
    if file_sha(baseline) != P["reference_checkpoint_sha256"]:
        raise ValueError("The inherited strong prior checkpoint changed")
    package = Path(__file__).resolve().parent
    proof = json.loads(oracle.read_text())
    if not proof["passed"] or proof["source_sha256"] != {name: file_sha(package / name) for name in proof["source_sha256"]}:
        raise ValueError("Independent production-density/LAX oracle is stale or failed")
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
    names = ["fullpath_model.py", "fullpath_lax.py", "fullpath_protocol.py", "fullpath_train.py",
             "fullpath_evaluate.py", "fullpath_oracle.py", "fullpath_qualify.py"]
    (output / "executed-source").mkdir()
    for name in names:
        shutil.copyfile(package / name, output / "executed-source" / name)
    shutil.copyfile(oracle, output / "INDEPENDENT_GRADIENT_ORACLE.json")
    write_json(output / "RUNTIME.json", {"python": platform.python_version(), "torch": torch.__version__,
        "threads": P["threads"], "cuda": torch.cuda.is_available(), "baseline_sha256": file_sha(baseline),
        "executed_source_sha256": {name: file_sha(package / name) for name in names},
        "audit_observer_loaded": False, "qualification_predictions": 0})
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    reference, observer = ControlledSnapshot.load(baseline), reference_observer(assets, "reward")
    selections = []
    for seed in ([17] if smoke else P["training_seeds"]):
        matched = []
        for arm, profile in (("lax_mean", mean), ("lax_risk", primary)):
            record, selection = fit(reference, corpus, observer, profile, primary, seed, arm,
                                    output / f"seed-{seed}-{arm}", steps_per_stage=1 if smoke else None)
            selections.append({"arm": arm, **selection}); matched.append(record)
        for field in ("schedule_sha256", "training_counts", "before_modules"):
            if matched[0][field] != matched[1][field]:
                raise ValueError(f"Matched training arms differ: {field}")
    write_json(output / "SELECTIONS.json", selections)
    risks = [row for row in selections if row["arm"] == "lax_risk"]
    means = {row["seed"]: row for row in selections if row["arm"] == "lax_mean"}
    gains = {"greedy": [], "same_law": [], "matched_mean": []}
    for row in risks:
        gains["greedy"].append(row["selected"]["quality_ce"] - row["candidates"][0]["quality_ce"])
        gains["same_law"].append(row["selected"]["quality_ce"] - row["candidates"][1]["quality_ce"])
        gains["matched_mean"].append(row["selected"]["quality_ce"] - means[row["seed"]]["selected"]["quality_ce"])
    gate = {"risk_gain_vs_greedy": float(np.mean(gains["greedy"])) >= .002,
            "risk_gain_vs_same_law": float(np.mean(gains["same_law"])) >= .002,
            "risk_gain_vs_matched_mean": float(np.mean(gains["matched_mean"])) >= 0,
            "at_least_one_learned_risk_selection": any(row["selected"]["path"] for row in risks),
            "retention_all_selected": all(row["selected"]["eligible"] for row in risks), "not_smoke": not smoke}
    write_json(output / "DEVELOPMENT_SEAL.json", {"profile_sha256": primary.digest,
        "protocol_sha256": file_sha(output / "PROTOCOL.json"), "selection_sha256": file_sha(output / "SELECTIONS.json"),
        "source_allocation_sha256": None if smoke else file_sha(output / "SOURCE_ALLOCATION.json"),
        "smoke_only": smoke, "qualification_predictions": 0, "admission_checks": gate,
        "development_gains": gains, "qualification_admitted": all(gate.values())})
    print(json.dumps({"development_admission": gate, "gains": gains}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "baseline", "output", "oracle"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    development(args.assets, args.baseline, args.output, args.oracle, args.smoke)
