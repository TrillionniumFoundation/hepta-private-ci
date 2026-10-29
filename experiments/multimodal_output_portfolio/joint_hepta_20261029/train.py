"""Bounded real-file joint learning and preregistered mechanism comparisons.

No synthetic result is reported as natural semantic generation. The main metric
always evaluates the inherited population gamma=2 NDU on full observed returns.
Gamma=0 and fixed policies are explicitly different training/control arms.
"""

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import torch
from torch.nn import functional as F

from experiments.multimodal_output_portfolio.unified_20261028.profile import certainty_equivalent
from .checkpoint import generation_metadata, save_checkpoint
from .learning import actor_score_loss, critic_log_moment_loss
from .mechanism_data import batch, select
from .media import utility
from .model import JointGenerator, supervised_loss, tensor_digest
from .runtime import cpu_seconds, execute, make_profile


PROTOCOL_PATH = Path(__file__).with_name("training_protocol.json")


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def coverage(model):
    result = {}
    for name, value in model.named_parameters():
        if value.grad is not None:
            finite = bool(torch.isfinite(value.grad).all())
            result[name] = {"finite": finite, "l1": value.grad.detach().abs().sum().item() if finite else None}
    return result


def pretrain(model, protocol, seed):
    rng = np.random.default_rng(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=protocol["pretraining_lr"])
    losses, best_gradient = [], {}
    for update in range(protocol["pretraining_updates"]):
        public, target = batch(rng.integers(0, 256, protocol["pretraining_batch"]).tolist())
        state = model.encode(public)
        # Rotate real state updates; all four adapters and shared Hepta influence heads.
        for action in ("shared", ("image", "audio", "video", "text")[update % 4], "shared"):
            state, _ = model.advance(state, action, public)
        loss = supervised_loss(model, state, target)
        optimizer.zero_grad(set_to_none=True); loss.backward()
        if update == protocol["pretraining_updates"]-1:
            best_gradient = coverage(model)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5, error_if_nonfinite=True)
        optimizer.step(); losses.append(loss.item())
    return {"initial_loss": losses[0], "final_loss": losses[-1], "updates": len(losses),
            "last_gradient": best_gradient, "loss_history": losses}


def compact_episode(episode, source, draw):
    row = episode.record
    return {"source": source, "draw": draw, "return": episode.net_return,
            "net_with_audit_close": row["net_with_audit_close"], "cost": row["actual_cost"],
            "utility": row["outcome"]["delivered_utility"],
            "actions": [a["action"] for a in row["actions"]],
            "wall_seconds": sum(a["wall_seconds"] for a in row["actions"]),
            "failure": row["failure"], "artifacts": row["outcome"]["artifact_sha256"],
            "profile_sha256": row["profile_sha256"], "contract_validated": row["contract_validated"]}


def joint_train(model, arm, protocol, seed, directory, profile):
    rng = np.random.default_rng(seed)
    actor_only = arm.endswith("actor_only")
    gamma = 2.0 if "risk" in arm else 0.0
    fixed = "fixed" in arm
    generator_parameters, actor_parameters, critic_parameters = [], [], []
    for name, parameter in model.named_parameters():
        if name.startswith("actor."):
            parameter.requires_grad_(not fixed); actor_parameters.append(parameter)
        elif name.startswith(("critic.", "delivery_critic.")):
            critic_parameters.append(parameter)
        else:
            parameter.requires_grad_(not actor_only); generator_parameters.append(parameter)
    groups = [{"params": generator_parameters, "lr": protocol["generator_lr"]},
              {"params": actor_parameters, "lr": protocol["actor_lr"]},
              {"params": critic_parameters, "lr": protocol["critic_lr"]}]
    optimizer = torch.optim.Adam(groups)
    before = tensor_digest(model.state_dict())
    gradient_max, score_gradient_max, logs, observed_episodes = {}, {}, [], 0
    for update in range(protocol["joint_updates"]):
        episodes, regularizers = [], []
        for draw in range(protocol["joint_batch"]):
            identity = int(rng.integers(0, 256))
            public, target = batch([identity])
            episode = execute(model, public, lambda sample: utility(sample, target).item(),
                directory/f"update-{update:04d}"/f"draw-{draw}", seed=int(rng.integers(1, 2**31)),
                context_id=f"train.{identity}", source_id=f"synthetic.train.{identity}", profile=profile,
                strategy="fixed" if fixed else "dynamic")
            episodes.append(episode)
            if not actor_only:
                regularizers.append(supervised_loss(model, episode.terminal_state, target))
        scores = torch.stack([e.log_probability for e in episodes])
        score_loss, statistics = actor_score_loss(scores, [e.net_return for e in episodes],
                                                 gamma=gamma, independent_episodes=True)
        values = torch.stack([v for e in episodes for v in e.critic_values])
        suffixes = [v for e in episodes for v in e.suffix_returns]
        critic_loss, critic_statistics = critic_log_moment_loss(values, suffixes, gamma=profile.ndu.gamma)
        auxiliary = torch.stack(regularizers).mean() if regularizers else score_loss.new_zeros(())
        loss = score_loss + critic_loss + protocol["supervised_weight_during_joint"] * auxiliary
        if update in (0, protocol["joint_updates"]-1):
            active = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
            score_gradients = torch.autograd.grad(score_loss, [p for _, p in active],
                                                  retain_graph=True, allow_unused=True)
            for (name, _), gradient in zip(active, score_gradients):
                if gradient is not None:
                    if not torch.isfinite(gradient).all():
                        raise ValueError(f"Nonfinite score-only gradient: {name}")
                    score_gradient_max[name] = max(score_gradient_max.get(name, 0), gradient.abs().sum().item())
        optimizer.zero_grad(set_to_none=True); loss.backward()
        for name, item in coverage(model).items():
            if not item["finite"]:
                raise ValueError(f"Nonfinite joint gradient: {name}")
            gradient_max[name] = max(gradient_max.get(name, 0), item["l1"])
        norms = [float(torch.nn.utils.clip_grad_norm_(g["params"], protocol["clip_each_parameter_group"],
                       error_if_nonfinite=True)) for g in groups]
        optimizer.step()
        observed_episodes += len(episodes)
        logs.append({"update": update, "score": float(score_loss.detach()), "critic": float(critic_loss.detach()),
                     "auxiliary": float(auxiliary.detach()), "gradient_group_norms": norms,
                     "mean_net": float(np.mean([e.net_return for e in episodes])),
                     "failures": sum(e.record["failure"] is not None for e in episodes)})
        if update % 16 == 0:
            print(json.dumps({"arm": arm, **logs[-1]}), flush=True)
    for parameter in model.parameters():
        parameter.requires_grad_(True)
    return {"arm": arm, "training_gamma": gamma, "evaluation_gamma": profile.ndu.gamma,
            "actual_episodes": observed_episodes, "initial_parameters_sha256": before,
            "final_parameters_sha256": tensor_digest(model.state_dict()),
            "gradient_max_l1_by_parameter": gradient_max, "updates": logs,
            "score_only_gradient_max_l1_by_parameter": score_gradient_max,
            "score_objective": "unnormalized_population_moment_with_independent_LOO",
            "physical_timing_direct_derivative_modelled": False,
            "auxiliary_supervised_weight": protocol["supervised_weight_during_joint"] if not actor_only else 0}


def evaluate(model, directory, profile, seed, *, sources=64, draws=2, strategy="dynamic", split="test",
             native_factory=None):
    rows = []
    with torch.no_grad():
        for source in range(sources):
            public, target = batch([source], split)
            for draw in range(draws):
                result = execute(model, public, lambda sample: utility(sample, target).item(),
                    directory/f"source-{source:03d}-draw-{draw}", seed=seed + source*7919 + draw*997,
                    context_id=f"{split}.{source}", source_id=f"synthetic.{split}.{source}", profile=profile,
                    strategy=strategy, native_factory=native_factory,
                    native_reopen_at=0 if native_factory and source == 0 and draw == 0 else None)
                rows.append(compact_episode(result, source, draw))
    returns = [r["return"] for r in rows]
    return {"rows": rows, "population_ce": certainty_equivalent(returns, profile.ndu.gamma),
            "population_ce_with_audit": certainty_equivalent([r["net_with_audit_close"] for r in rows], profile.ndu.gamma),
            "mean_net": float(np.mean(returns)), "mean_cost": float(np.mean([r["cost"] for r in rows])),
            "mean_utility": float(np.mean([r["utility"] for r in rows])),
            "failures": sum(r["failure"] is not None for r in rows), "sources": sources,
            "actual_draws": len(rows), "strategy": strategy, "empirical_CE_has_finite_sample_bias": True}


def paired_comparison(left, right, seed, replicates=1000):
    identities = [{(r["source"], r["draw"]) for r in side["rows"]} for side in (left, right)]
    if identities[0] != identities[1] or any(len(keys) != len(side["rows"]) for keys, side in zip(identities, (left, right))):
        raise ValueError("Paired source/draw identities are incomplete or repeated")
    pairs = {}
    for label, result in (("left", left), ("right", right)):
        for row in result["rows"]:
            pairs.setdefault(row["source"], {}).setdefault(label, []).append(row["return"])
    if any(set(v) != {"left", "right"} for v in pairs.values()):
        raise ValueError("Paired evaluation sources differ")
    names, rng = sorted(pairs), np.random.default_rng(seed)
    def difference(indices):
        return (certainty_equivalent([r for i in indices for r in pairs[i]["left"]], 2)
                - certainty_equivalent([r for i in indices for r in pairs[i]["right"]], 2))
    samples = [difference(rng.choice(names, len(names), replace=True)) for _ in range(replicates)]
    lower, upper = np.quantile(samples, [.025, .975])
    sealed_difference = left["population_ce_with_audit"] - right["population_ce_with_audit"]
    return {"ce_difference_registered_complete_serving_cost": difference(names),
            "ce_difference_including_final_audit_seal_sensitivity": sealed_difference,
            "source_bootstrap_95": [float(lower), float(upper)],
            "unique_sources": len(names), "replicates": replicates, "positive_lower_bound": bool(lower > 0),
            "excludes_training_seed_uncertainty": True}


def distill(model, protocol, seed, directory, profile):
    examples = []
    started, cpu = time.perf_counter(), cpu_seconds()
    with torch.no_grad():
        for identity in range(protocol["distillation_train_sources"]):
            public, target = batch([identity], "development")
            result = execute(model, public, lambda sample: utility(sample, target).item(), directory/f"teacher-{identity}",
                seed=seed+identity, context_id=f"development.{identity}", source_id=f"synthetic.development.{identity}",
                profile=profile, strategy="planner")
            examples.extend(result.teacher_examples)
    student = deepcopy(model)
    x = torch.cat([v[0] for v in examples]); y = torch.tensor([v[1] for v in examples])
    optimizer = torch.optim.Adam(student.actor.parameters(), lr=0.002)
    losses = []
    for _ in range(protocol["distillation_updates"]):
        loss = F.cross_entropy(student.actor(x), y)
        optimizer.zero_grad(set_to_none=True); loss.backward(); optimizer.step()
        losses.append(float(loss.detach()))
    training_seconds = {"wall": time.perf_counter()-started, "cpu": cpu_seconds()-cpu}
    sources = protocol["distillation_test_sources"]
    teacher = evaluate(model, directory/"teacher-test", profile, seed+900000, sources=sources, strategy="planner")
    deployed = evaluate(student, directory/"student-test", profile, seed+900000, sources=sources, strategy="greedy")
    return student, {"teacher": teacher, "student": deployed, "distillation_loss": [losses[0], losses[-1]],
        "training_seconds": training_seconds, "approximate_teacher": True,
        "ce_change": deployed["population_ce_with_audit"]-teacher["population_ce_with_audit"],
        "cost_change": deployed["mean_cost"]-teacher["mean_cost"],
        "examples": len(examples), "teacher_target_selection": "frozen_development_only"}


def run(output, *, seed=17, width=32, smoke=False, native_binary=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(PROTOCOL_PATH.read_text())
    if seed not in protocol["seeds"] or width not in protocol["widths"]:
        raise ValueError("Unregistered replication or scale")
    if smoke:
        protocol.update(pretraining_updates=4, joint_updates=2, joint_batch=2,
                        distillation_train_sources=2, distillation_updates=4, distillation_test_sources=2,
                        bootstrap_replicates=30)
    torch.set_num_threads(2); torch.use_deterministic_algorithms(True)
    start, cpu = time.perf_counter(), cpu_seconds()
    profile = make_profile()
    write(output/"PROFILE.json", profile.to_dict()); write(output/"EXECUTED_PROTOCOL.json", protocol)
    result = {"schema": "hepta.joint-generation.study.v1", "seed": seed, "width": width,
              "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(), "smoke": smoke,
              "profile_sha256": profile.digest, "pretraining": {}, "arms": {}, "comparisons": {},
              "runtime": {"python": platform.python_version(), "torch": torch.__version__, "threads": 2},
              "natural_semantic_qualification": False, "original_reserved_cohorts_used": False}
    bases = {}
    for mode in ("ordinary", "dual"):
        torch.manual_seed(seed)
        base = JointGenerator(width=width, mode=mode)
        result["pretraining"][mode] = pretrain(base, protocol, seed)
        bases[mode] = base
    for arm in protocol["arms"]:
        model = deepcopy(bases["ordinary" if arm.startswith("ordinary") else "dual"])
        arm_start, arm_cpu = time.perf_counter(), cpu_seconds()
        training = joint_train(model, arm, protocol, seed+1000, output/arm/"training", profile)
        training["wall_seconds"] = time.perf_counter()-arm_start
        training["cpu_seconds"] = cpu_seconds()-arm_cpu
        evaluation = evaluate(model, output/arm/"test", profile, seed+200000, sources=4 if smoke else 64,
                              strategy="fixed" if "fixed" in arm else "dynamic")
        result["arms"][arm] = {"training": training, "evaluation": evaluation,
                               "parameters": sum(p.numel() for p in model.parameters())}
        public, _ = batch([0])
        save_checkpoint(output/arm/"MODEL.pt", model, model.encode(public),
                        torch.Generator().manual_seed(seed), profile, public,
                        metadata=generation_metadata(model, public, profile, arm=arm, study_seed=seed, qualification=False))
        if arm == "hepta_dynamic_risk":
            student, distilled = distill(model, protocol, seed, output/"distillation", profile)
            result["distillation"] = distilled
            save_checkpoint(output/"distillation"/"STUDENT.pt", student, student.encode(public),
                            torch.Generator().manual_seed(seed), profile, public,
                            metadata=generation_metadata(student, public, profile, arm="distilled", qualification=False))
            if native_binary:
                from .native_bridge import NativeGuard
                def factory(model_sha, profile_sha, directory):
                    return NativeGuard(binary=native_binary, directory=directory, case="joint.generated",
                        model_sha256=model_sha, profile_sha256=profile_sha,
                        allowed_actions=("shared", "image", "audio", "video", "text", "verify", "delivery", "stop"))
                result["native_deployment"] = evaluate(student, output/"native", profile, seed+700000,
                                                        sources=2, draws=1, strategy="greedy", native_factory=factory)
        write(output/"RESULTS.partial.json", result)
    for left, right, label in protocol["paired_comparisons"]:
        result["comparisons"][label] = paired_comparison(result["arms"][left]["evaluation"],
            result["arms"][right]["evaluation"], seed, protocol["bootstrap_replicates"])
    result["all_primary_lower_bounds_positive"] = all(r["positive_lower_bound"] for r in result["comparisons"].values())
    result["research_effect_qualified"] = False  # Requires all six registered replications and natural gate.
    result["total_wall_seconds"], result["total_cpu_seconds"] = time.perf_counter()-start, cpu_seconds()-cpu
    write(output/"RESULTS.json", result)
    summary = {k: result[k] for k in ("seed", "width", "smoke", "comparisons", "total_wall_seconds", "total_cpu_seconds", "profile_sha256", "protocol_sha256")}
    summary["arms"] = {name: {"evaluation": {k: v for k, v in item["evaluation"].items() if k != "rows"},
                               "parameters": item["parameters"],
                               "actual_training_episodes": item["training"]["actual_episodes"],
                               "score_nonzero_parameter_tensors": sum(v > 0 for v in item["training"]["score_only_gradient_max_l1_by_parameter"].values()),
                               "parameter_snapshot": item["training"]["final_parameters_sha256"]}
                       for name, item in result["arms"].items()}
    summary["distillation"] = {k: v for k, v in result["distillation"].items() if k not in ("teacher", "student")}
    summary["native_deployment"] = ({k: v for k, v in result["native_deployment"].items() if k != "rows"}
                                      if "native_deployment" in result else None)
    write(output/"SUMMARY.json", summary)
    print("RESULT_JSON=" + json.dumps(summary, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", default=17, type=int)
    parser.add_argument("--width", default=32, type=int)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--native-binary", type=Path)
    args = parser.parse_args()
    run(args.output, seed=args.seed, width=args.width, smoke=args.smoke, native_binary=args.native_binary)
