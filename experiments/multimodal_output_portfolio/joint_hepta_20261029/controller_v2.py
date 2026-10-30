"""Development controller training with conditional score baselines and DAgger.

The old study remains unchanged evidence. This runner uses new development
namespaces and never consumes a confirmation cohort. Every RL return comes
from an actual four-file trajectory. Conditional baseline subtraction changes
variance, not the population moment objective; lower variance is measured,
not assumed. Supervised prefix training/anchoring changes the pure objective.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch
from torch.nn import functional as F

from .checkpoint import generation_metadata, save_checkpoint
from .learning import critic_log_moment_loss, population_metrics
from .mechanism_data import batch
from .media import utility
from .model import ACTIONS, JointGenerator, supervised_loss, tensor_digest
from .runtime import HORIZON, TARIFF, cpu_seconds, execute, make_profile
from .train import compact_episode, coverage, paired_comparison, write


PROTOCOL_PATH = Path(__file__).with_name("controller_v2_protocol.json")


def elapsed(start):
    wall, cpu = time.perf_counter() - start[0], cpu_seconds() - start[1]
    return {"wall_seconds": wall, "cpu_seconds": cpu,
            "physical_cost": TARIFF["wall_second"] * wall + TARIFF["cpu_second"] * cpu}


def _baseline(value, prefix_cost, gamma, bound):
    """A detached, predictable control variate, including sunk-cost origin."""
    value = value.detach()
    if not bool(torch.isfinite(value)) or prefix_cost < 0 or not np.isfinite(prefix_cost):
        raise ValueError("Predictable baseline inputs must be finite with nonnegative past cost")
    log_value = value + 2 * prefix_cost
    clipped = log_value.clamp(-bound, bound)
    # Gamma0 uses a CE predictor only as a baseline, never as a mean critic.
    result = clipped / 2 if gamma == 0 else torch.expm1(clipped) / 2
    return result, int(float(clipped) != float(log_value))


def conditional_score_loss(episodes, *, gamma=2.0, baseline_log_bound=12.0,
                           independent_episodes=False):
    """Unnormalised moment score with one pre-draw baseline per random choice.

    Given prefix cost C and critic v predicting log E exp(-2 R_suffix), the
    risk baseline is (exp(2C+v)-1)/2. No critic gradient is propagated. The
    baseline may be inaccurate; any finite predictable baseline stays unbiased.
    Other independently drawn trajectories provide a residual LOO correction
    from their initial states, never this trajectory's own final return.
    """
    if gamma not in (0.0, 2.0) or not episodes or baseline_log_bound <= 0:
        raise ValueError("Unsupported objective or empty score batch")
    if len(episodes) > 1 and independent_episodes is not True:
        raise ValueError("Residual LOO requires independent episode choices")
    reference = episodes[0].log_probability
    returns = reference.new_tensor([e.net_return for e in episodes]).detach()
    moments = -returns if gamma == 0 else torch.expm1(-gamma * returns) / gamma
    if not bool(torch.isfinite(moments).all()):
        raise ValueError("Actual moment overflow; returns and targets are never clipped")
    initial, clipped_count = [], 0
    for episode in episodes:
        value, clipped = _baseline(episode.critic_values[0], 0.0, gamma, baseline_log_bound)
        initial.append(value); clipped_count += clipped
    residual = moments - torch.stack(initial)
    corrections = ((residual.sum() - residual) / (len(episodes) - 1)
                   if len(episodes) > 1 else torch.zeros_like(residual))
    old_loo = ((moments.sum() - moments) / (len(episodes) - 1)
               if len(episodes) > 1 else torch.zeros_like(moments))
    losses, coefficients, old_coefficients = [], [], []
    for index, episode in enumerate(episodes):
        if not episode.score_terms:
            raise ValueError("No sampled conditional scores in a joint training episode")
        summed = torch.stack([term.log_probability for term in episode.score_terms]).sum()
        if not torch.allclose(summed.detach(), episode.log_probability.detach(), rtol=1e-5, atol=1e-4):
            raise ValueError("Conditional scores do not reconstruct the declared joint law")
        terms = []
        for term in episode.score_terms:
            baseline, clipped = _baseline(term.prior_log_moment, term.prefix_cost,
                                          gamma, baseline_log_bound)
            clipped_count += clipped
            coefficient = (moments[index] - baseline - corrections[index]).detach()
            terms.append(coefficient * term.log_probability)
            coefficients.append(float(coefficient))
            old_coefficients.append(float(moments[index] - old_loo[index]))
        losses.append(torch.stack(terms).sum())
    loss = torch.stack(losses).mean()
    return loss, {**population_metrics(returns), "training_gamma": gamma,
        "baseline": "pre_draw_conditional_plus_other_independent_episode_residual_LOO",
        "moment_objective_estimate": float(moments.mean()),
        "coefficient_mean_square": float(np.mean(np.square(coefficients))),
        "v1_loo_coefficient_mean_square_on_same_draws": float(np.mean(np.square(old_coefficients))),
        "coefficient_diagnostic_is_not_gradient_variance": True,
        "conditional_score_terms": len(coefficients), "baseline_only_clipped": clipped_count,
        "self_normalized_risk_gradient": False, "critic_gradient_in_score": False,
        "unbiased_before_optimizer_given_complete_law_and_exogenous_timing": True}


def pretrain_prefixes(model, protocol, seed):
    rng = np.random.default_rng(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=protocol["pretraining_lr"])
    losses, prefix_counts, initial = [], {}, tensor_digest(model.state_dict())
    for update in range(protocol["pretraining_updates"]):
        public, target = batch(rng.integers(protocol["train_sources"],
            size=protocol["pretraining_batch"]).tolist(), protocol["train_namespace"])
        state = model.encode(public)
        terms = [supervised_loss(model, state, target)]
        length = int(rng.integers(1, HORIZON + 1))
        for step in range(length):
            action = ACTIONS[int(rng.integers(len(ACTIONS) - 1))]
            state, _ = model.advance(state, action, public)
            terms.append(supervised_loss(model, state, target))
            prefix_counts[str(step + 1)] = prefix_counts.get(str(step + 1), 0) + 1
        loss = torch.stack(terms).mean()
        optimizer.zero_grad(set_to_none=True); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5, error_if_nonfinite=True)
        optimizer.step(); losses.append(float(loss.detach()))
    return {"updates": len(losses), "loss_history": losses, "prefix_supervision_counts": prefix_counts,
            "initial_parameters_sha256": initial, "final_parameters_sha256": tensor_digest(model.state_dict()),
            "target_access": "supervised training only", "last_gradient": coverage(model)}


def joint_train(model, arm, protocol, seed, directory, profile):
    rng = np.random.default_rng(seed)
    actor_only, fixed = arm.endswith("actor_only"), "fixed" in arm
    gamma = 2.0 if "risk" in arm else 0.0
    groups = {"generator": [], "actor": [], "critic": []}
    for name, parameter in model.named_parameters():
        group = "actor" if name.startswith("actor.") else "critic" if name.startswith(("critic.", "delivery_critic.")) else "generator"
        parameter.requires_grad_(not (group == "actor" and fixed or group == "generator" and actor_only))
        groups[group].append(parameter)
    optimizer = torch.optim.Adam([{"params": values, "lr": protocol[name + "_lr"]}
                                  for name, values in groups.items()])
    initial, logs, gradients = tensor_digest(model.state_dict()), [], {}
    for update in range(protocol["joint_updates"]):
        episodes, anchors = [], []
        for draw in range(protocol["joint_batch"]):
            identity = int(rng.integers(protocol["train_sources"]))
            public, target = batch([identity], protocol["train_namespace"])
            episode = execute(model, public, lambda sample: utility(sample, target).item(),
                directory / f"update-{update:04d}" / f"draw-{draw}", seed=int(rng.integers(1, 2**31)),
                context_id=f"{protocol['train_namespace']}.{identity}",
                source_id=f"synthetic.{protocol['train_namespace']}.{identity}", profile=profile,
                strategy="fixed" if fixed else "dynamic")
            episodes.append(episode)
            if not actor_only:
                anchors.append(supervised_loss(model, episode.terminal_state, target))
        score, stats = conditional_score_loss(episodes, gamma=gamma, independent_episodes=True,
            baseline_log_bound=protocol["baseline_log_bound"])
        critic, _ = critic_log_moment_loss(torch.stack([v for e in episodes for v in e.critic_values]),
            [v for e in episodes for v in e.suffix_returns], gamma=profile.ndu.gamma)
        auxiliary = torch.stack(anchors).mean() if anchors else score.new_zeros(())
        loss = score + critic + protocol["supervised_weight_during_joint"] * auxiliary
        if update in (0, protocol["joint_updates"] - 1):
            active = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
            values = torch.autograd.grad(score, [p for _, p in active], retain_graph=True, allow_unused=True)
            for (name, _), value in zip(active, values):
                if value is not None:
                    if not bool(torch.isfinite(value).all()):
                        raise ValueError("Nonfinite score-only gradient")
                    gradients[name] = max(gradients.get(name, 0.0), float(value.abs().sum()))
        optimizer.zero_grad(set_to_none=True); loss.backward()
        norms = {name: float(torch.nn.utils.clip_grad_norm_(values,
            protocol["clip_each_parameter_group"], error_if_nonfinite=True)) for name, values in groups.items()}
        optimizer.step()
        logs.append({"update": update, "score_loss": float(score.detach()), "critic_loss": float(critic.detach()),
            "auxiliary": float(auxiliary.detach()), "gradient_norms": norms, "score_diagnostics": stats,
            "actual_episodes": len(episodes), "failures": sum(e.record["failure"] is not None for e in episodes)})
        if update % 16 == 0:
            print(json.dumps({"arm": arm, **logs[-1]}), flush=True)
    for parameter in model.parameters():
        parameter.requires_grad_(True)
    return {"arm": arm, "training_gamma": gamma, "actual_episodes": protocol["joint_updates"] * protocol["joint_batch"],
        "initial_parameters_sha256": initial, "final_parameters_sha256": tensor_digest(model.state_dict()),
        "updates": logs, "score_only_gradient_max_l1_by_parameter": gradients,
        "auxiliary_supervised_weight": 0 if actor_only else protocol["supervised_weight_during_joint"],
        "physical_timing_direct_derivative_modelled": False}


def evaluate(model, directory, profile, seed, width, arm, protocol, strategy="dynamic"):
    rows = []
    namespace = protocol["development_namespace"]
    with torch.no_grad():
        for source in range(protocol["development_sources"]):
            public, target = batch([source], namespace)
            for draw in range(protocol["evaluation_draws_per_source"]):
                episode = execute(model, public, lambda sample: utility(sample, target).item(),
                    directory / f"source-{source:03d}-draw-{draw}", seed=seed + 200000 + source * 7919 + draw * 997,
                    context_id=f"{namespace}.{source}", source_id=f"synthetic.{namespace}.{source}",
                    profile=profile, strategy=strategy)
                row = {**compact_episode(episode, source, draw), "seed": seed, "width": width,
                       "arm": arm, "source_namespace": namespace}
                row["cost_by_kind"] = {kind: sum(c["amount"] for c in episode.record["outcome"]["costs"]
                                                if c["kind"] == kind)
                                       for kind in {c["kind"] for c in episode.record["outcome"]["costs"]}}
                row["audit_close_cost"] = episode.net_return - episode.record["net_with_audit_close"]
                rows.append(row)
    returns = [r["return"] for r in rows]
    return {"rows": rows, "population_ce": population_metrics(returns)["population_ce_plugin"],
        "population_ce_with_audit": population_metrics([r["net_with_audit_close"] for r in rows])["population_ce_plugin"],
        "mean_net": float(np.mean(returns)), "mean_cost": float(np.mean([r["cost"] for r in rows])),
        "mean_utility": float(np.mean([r["utility"] for r in rows])),
        "failures": sum(r["failure"] is not None for r in rows), "sources": protocol["development_sources"],
        "actual_draws": len(rows), "strategy": strategy, "confirmation": False,
        "empirical_CE_has_finite_sample_bias": True}


def distill_dagger(model, directory, profile, protocol, seed, width):
    """Planner labels on student-visited states; generator/critics remain frozen.

    These teacher computations occur in training trajectories and are charged
    there. Deployment uses the plain greedy actor, with no hidden planner query.
    The teacher is an approximate value model, not an oracle or quality proof.
    """
    student, examples, logs, failures = deepcopy(model), [], [], 0
    frozen = {n: p.detach().clone() for n, p in model.named_parameters() if not n.startswith("actor.")}
    optimizer = torch.optim.Adam(student.actor.parameters(), lr=protocol["distillation_lr"])
    for round_index in range(protocol["distillation_rounds"]):
        with torch.no_grad():
            for source in range(protocol["distillation_sources_per_round"]):
                identity = source + round_index * protocol["distillation_sources_per_round"]
                public, target = batch([identity], protocol["distillation_namespace"])
                episode = execute(student, public, lambda sample: utility(sample, target).item(),
                    directory / "training" / f"round-{round_index}" / f"source-{source}",
                    seed=seed + 800000 + identity, context_id=f"distillation.{identity}",
                    source_id=f"synthetic.{protocol['distillation_namespace']}.{identity}",
                    profile=profile, strategy="greedy", collect_planner_labels=True)
                examples.extend(episode.teacher_examples)
                failures += episode.record["failure"] is not None
        x, y = torch.cat([e[0] for e in examples]), torch.tensor([e[1] for e in examples])
        for _ in range(protocol["distillation_updates_per_round"]):
            loss = F.cross_entropy(student.actor(x), y)
            optimizer.zero_grad(set_to_none=True); loss.backward(); optimizer.step()
        logs.append({"round": round_index, "examples": len(examples), "loss": float(loss.detach())})
    if any(not torch.equal(dict(student.named_parameters())[n].detach(), value) for n, value in frozen.items()):
        raise ValueError("DAgger changed the frozen teacher generator or critics")
    return student, {"rounds": logs, "actual_training_episodes": protocol["distillation_rounds"] * protocol["distillation_sources_per_round"],
        "teacher": "same frozen approximate planner queried on student states",
        "targets": "planner labels at student-visited public states in the distillation namespace",
        "generator_and_critics_unchanged": True, "failures": failures, "promotion": False}


def run(output, *, seed=17, width=32, smoke=False):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(PROTOCOL_PATH.read_text())
    if seed not in protocol["seeds"] or width not in protocol["widths"]:
        raise ValueError("Unregistered development seed or width")
    if smoke:
        protocol.update(pretraining_updates=3, pretraining_batch=2, joint_updates=2, joint_batch=2,
            development_sources=2, evaluation_draws_per_source=1, bootstrap_replicates=30,
            distillation_rounds=2, distillation_sources_per_round=1, distillation_updates_per_round=2)
    torch.set_num_threads(2); torch.use_deterministic_algorithms(True)
    profile = make_profile()
    result = {"schema": "hepta.joint-generation.controller-v2.development.v1", "stage": "development",
        "seed": seed, "width": width, "smoke": smoke, "profile_sha256": profile.digest,
        "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
        "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("controller_v2.py", "controller_v2_protocol.json", "runtime.py", "model.py",
                                       "hepta_core.py", "learning.py", "train.py", "checkpoint.py", "contract.py",
                                       "media.py", "mechanism_data.py")},
        "pretraining": {}, "arms": {}, "comparisons": {}, "phase_costs": {},
        "runtime": {"python": platform.python_version(), "torch": str(torch.__version__), "threads": 2},
        "research_effect_qualified": False, "semantic_qualification": False,
        "confirmation_sources_consumed": 0, "old_test_sources_used": False}
    write(output / "PROFILE.json", profile.to_dict()); write(output / "EXECUTED_PROTOCOL.json", protocol)
    start = (time.perf_counter(), cpu_seconds())
    bases = {}
    for mode in ("ordinary", "dual"):
        phase = (time.perf_counter(), cpu_seconds()); torch.manual_seed(seed)
        base = JointGenerator(width=width, mode=mode)
        result["pretraining"][mode] = pretrain_prefixes(base, protocol, seed)
        result["phase_costs"][f"pretraining.{mode}"] = elapsed(phase)
        bases[mode] = base
    risk_model = None
    for arm in protocol["arms"]:
        model = deepcopy(bases["ordinary" if arm.startswith("ordinary") else "dual"])
        phase = (time.perf_counter(), cpu_seconds())
        training = joint_train(model, arm, protocol, seed + 1000, output / arm / "training", profile)
        result["phase_costs"][f"training.{arm}"] = elapsed(phase)
        phase = (time.perf_counter(), cpu_seconds())
        evaluation = evaluate(model, output / arm / "development", profile, seed, width, arm, protocol,
                              strategy="fixed" if "fixed" in arm else "dynamic")
        result["phase_costs"][f"evaluation.{arm}"] = elapsed(phase)
        public, _ = batch([0], protocol["train_namespace"])
        checkpoint = save_checkpoint(output / arm / "MODEL.pt", model, model.encode(public),
            torch.Generator().manual_seed(seed), profile, public,
            metadata=generation_metadata(model, public, profile, arm=arm, stage="development", qualification=False,
                                         protocol_sha256=result["protocol_sha256"], training_source_sha256=result["source_sha256"]))
        result["arms"][arm] = {"training": training, "evaluation": evaluation, "checkpoint": checkpoint,
                               "parameters": sum(p.numel() for p in model.parameters())}
        if arm == "hepta_dynamic_risk":
            risk_model = model
        write(output / "RESULTS.partial.json", result)
    for left, right, label in protocol["paired_comparisons"]:
        result["comparisons"][label] = paired_comparison(result["arms"][left]["evaluation"],
            result["arms"][right]["evaluation"], seed, protocol["bootstrap_replicates"])
    phase = (time.perf_counter(), cpu_seconds())
    student, distillation = distill_dagger(risk_model, output / "distillation", profile, protocol, seed, width)
    result["phase_costs"]["distillation.training"] = elapsed(phase)
    for label, candidate, strategy in (("teacher", risk_model, "planner"), ("student", student, "greedy")):
        phase = (time.perf_counter(), cpu_seconds())
        distillation[label] = evaluate(candidate, output / "distillation" / label, profile,
            seed, width, "hepta_" + label, protocol, strategy=strategy)
        result["phase_costs"][f"distillation.evaluation.{label}"] = elapsed(phase)
    distillation["comparison"] = paired_comparison(distillation["student"], distillation["teacher"],
        seed, protocol["bootstrap_replicates"])
    public, _ = batch([0], protocol["train_namespace"])
    distillation["checkpoint"] = save_checkpoint(output / "distillation" / "STUDENT.pt", student,
        student.encode(public), torch.Generator().manual_seed(seed), profile, public,
        metadata=generation_metadata(student, public, profile, arm="distilled", stage="development", qualification=False,
                                     protocol_sha256=result["protocol_sha256"], training_source_sha256=result["source_sha256"]))
    result["distillation"] = distillation
    result["measured_runner_total"] = elapsed(start)
    write(output / "RESULTS.json", result)
    summary = {k: v for k, v in result.items() if k not in ("arms", "pretraining", "distillation")}
    summary["arms"] = {n: {"evaluation": {k: v for k, v in a["evaluation"].items() if k != "rows"},
                           "checkpoint": a["checkpoint"], "parameters": a["parameters"],
                           "actual_training_episodes": a["training"]["actual_episodes"]}
                       for n, a in result["arms"].items()}
    summary["distillation"] = {k: v for k, v in distillation.items() if k not in ("teacher", "student")}
    write(output / "SUMMARY.json", summary)
    print("RESULT_JSON=" + json.dumps(summary, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    run(args.output, seed=args.seed, width=args.width, smoke=args.smoke)
