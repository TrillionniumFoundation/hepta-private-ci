"""Content/policy factorial with actual-file returns and a legal initial STOP."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..learning import actor_score_loss, critic_log_moment_loss, population_metrics
from ..mechanism_data import batch
from ..media import utility
from ..model import ACTIONS, supervised_loss, tensor_digest
from ..runtime import cpu_seconds
from .profile import TARIFF
from .runtime import execute


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def clock():
    return time.perf_counter(), cpu_seconds()


def elapsed(start):
    wall, cpu = time.perf_counter()-start[0], cpu_seconds()-start[1]
    return {"wall_seconds": wall, "cpu_seconds": cpu,
            "physical_cost": wall*TARIFF["wall_second"]+cpu*TARIFF["cpu_second"]}


def parameter_group(name):
    return ("actor" if name.startswith("actor.") else "critic"
            if name.startswith(("critic.", "delivery_critic.")) else "generator")


def group_hashes(model):
    return {group: tensor_digest({n: p for n, p in model.named_parameters() if parameter_group(n) == group})
            for group in ("generator", "actor", "critic")}


def save_model(path, model, metadata):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"schema": "hepta.generation.trained-parameters.v3", "config": model.config,
                "state_dict": model.state_dict(), "metadata": metadata}, path)
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "parameters_sha256": tensor_digest(model.state_dict()),
            "parameters": sum(p.numel() for p in model.parameters()), "config": model.config}


def pretrain(model, protocol, seed):
    """Supervise the initial encoding and every sampled nonterminal prefix.

    Initial STOP is meaningful only when the encoder's existing content is also
    trained. Targets occur in this training function, never in model.policy.
    """
    rng = np.random.default_rng(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=protocol["pretraining_lr"])
    initial, losses, counts = group_hashes(model), [], {str(i): 0 for i in range(7)}
    for update in range(protocol["pretraining_updates"]):
        public, target = batch(rng.integers(protocol["train_sources"],
            size=protocol["pretraining_batch"]).tolist(), protocol["train_namespace"])
        state = model.encode(public)
        terms = [supervised_loss(model, state, target)]; counts["0"] += 1
        for step in range(int(rng.integers(1, 7))):
            action = ACTIONS[int(rng.integers(6))]
            state, _ = model.advance(state, action, public)
            terms.append(supervised_loss(model, state, target)); counts[str(step+1)] += 1
        loss = torch.stack(terms).mean()
        optimizer.zero_grad(set_to_none=True); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0, error_if_nonfinite=True)
        optimizer.step(); losses.append(float(loss.detach()))
    return {"loss_history": losses, "prefix_supervision_counts": counts,
            "initial_group_hashes": initial, "final_group_hashes": group_hashes(model),
            "target_access": "training only; initial and sampled nonterminal content"}


def joint_train(model, *, content, policy, protocol, seed, directory, profile):
    if content not in {"frozen", "joint"} or policy not in {"fixed", "dynamic"}:
        raise ValueError("Unregistered factorial arm")
    rng, directory = np.random.default_rng(seed), Path(directory)
    groups = {name: [] for name in ("generator", "actor", "critic")}
    for name, parameter in model.named_parameters():
        group = parameter_group(name)
        active = not (group == "generator" and content == "frozen" or group == "actor" and policy == "fixed")
        parameter.requires_grad_(active); groups[group].append(parameter)
    optimizer = torch.optim.Adam([{"params": values, "lr": protocol[name+"_lr"]}
                                  for name, values in groups.items()])
    initial, logs, score_coverage = group_hashes(model), [], {}
    initial_stops, initial_decisions, failures, total_episode_cost = 0, 0, 0, 0.0
    for update in range(protocol["joint_updates"]):
        episodes = []
        for draw in range(protocol["joint_batch"]):
            identity = int(rng.integers(protocol["train_sources"]))
            public, target = batch([identity], protocol["train_namespace"])
            episode = execute(model, public, lambda result: utility(result, target).item(),
                directory/f"update-{update:04d}"/f"draw-{draw}", seed=int(rng.integers(1, 2**31)),
                context_id=f"{protocol['train_namespace']}.{identity}",
                source_id=f"synthetic.{protocol['train_namespace']}.{identity}", profile=profile,
                strategy=policy, fixed_actions=tuple(protocol["fixed_actions"]))
            episodes.append(episode); initial_decisions += 1
            initial_stops += bool(episode.record["actions"] and episode.record["actions"][0]["action"] == "stop")
            failures += episode.record["failure"] is not None
            total_episode_cost += episode.record["actual_cost"]
        score, stats = actor_score_loss(torch.stack([e.log_probability for e in episodes]),
            [e.net_return for e in episodes], gamma=2.0, independent_episodes=True)
        critic, _ = critic_log_moment_loss(torch.stack([v for e in episodes for v in e.critic_values]),
                                          [r for e in episodes for r in e.suffix_returns], gamma=2.0)
        if score.requires_grad and update in (0, protocol["joint_updates"]-1):
            active = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
            gradients = torch.autograd.grad(score, [p for _, p in active], retain_graph=True, allow_unused=True)
            for (name, _), gradient in zip(active, gradients):
                if gradient is not None:
                    if not bool(torch.isfinite(gradient).all()):
                        raise ValueError("Nonfinite task score gradient")
                    score_coverage[name] = max(score_coverage.get(name, 0.0), float(gradient.abs().sum()))
                    if name == "actor.2.weight":
                        score_coverage["initial_stop_actor_output_row_max_l1"] = max(
                            score_coverage.get("initial_stop_actor_output_row_max_l1", 0.0),
                            float(gradient[-1].abs().sum()))
        loss = score + critic
        optimizer.zero_grad(set_to_none=True); loss.backward()
        norms = {name: float(torch.nn.utils.clip_grad_norm_(values,
                    protocol["clip_each_parameter_group"], error_if_nonfinite=True))
                 for name, values in groups.items()}
        optimizer.step()
        logs.append({"update": update, "score_loss": float(score.detach()), "critic_loss": float(critic.detach()),
                     "gradient_norms_before_clipping": norms, "score_statistics": stats,
                     "actual_episodes": len(episodes), "failures": sum(e.record["failure"] is not None for e in episodes)})
    final = group_hashes(model)
    if content == "frozen" and initial["generator"] != final["generator"]:
        raise AssertionError("Frozen content parameters changed")
    if policy == "fixed" and initial["actor"] != final["actor"]:
        raise AssertionError("Fixed policy actor parameters changed")
    for parameter in model.parameters():
        parameter.requires_grad_(True)
    return {"content_training": content, "policy": policy, "updates": logs,
            "initial_group_hashes": initial, "final_group_hashes": final,
            "initial_stop_samples": initial_stops, "initial_decisions": initial_decisions,
            "score_only_gradient_max_l1": score_coverage, "failures": failures,
            "total_episode_cost": total_episode_cost, "actual_episodes": initial_decisions,
            "supervised_weight_during_joint": 0.0, "training_gamma": 2.0,
            "physical_timing_direct_derivative_modelled": False}


def evaluate(model, directory, profile, *, seed, protocol, strategy="dynamic", prefix=()):
    rows, namespace = [], protocol["development_namespace"]
    with torch.no_grad():
        for source in range(protocol["development_sources"]):
            public, target = batch([source], namespace)
            for draw in range(protocol["evaluation_draws_per_source"]):
                episode = execute(model, public, lambda result: utility(result, target).item(),
                    Path(directory)/f"source-{source:03d}-draw-{draw}",
                    seed=seed+200000+source*7919+draw*997,
                    context_id=f"{namespace}.{source}", source_id=f"synthetic.{namespace}.{source}",
                    profile=profile, strategy=strategy, prefix=prefix,
                    fixed_actions=tuple(protocol["fixed_actions"]))
                record = episode.record
                rows.append({"source": source, "draw": draw, "source_namespace": namespace,
                    "return": episode.net_return, "utility": record["outcome"]["delivered_utility"],
                    "cost": record["actual_cost"], "actions": [a["action"] for a in record["actions"]],
                    "failure": record["failure"], "artifacts": record["outcome"]["artifact_sha256"],
                    "initial_snapshot_sha256": record["initial_snapshot_sha256"],
                    "model_sha256": record["parameter_snapshot_sha256"], "profile_sha256": profile.digest,
                    "cost_by_kind": {kind: sum(e["amount"] for e in record["events"] if e["action"] == kind)
                                     for kind in {e["action"] for e in record["events"]}}})
    return {"rows": rows, **population_metrics([r["return"] for r in rows]),
            "mean_cost": float(np.mean([r["cost"] for r in rows])),
            "mean_utility": float(np.mean([r["utility"] for r in rows])),
            "initial_stop_rate": float(np.mean([r["actions"][0] == "stop" for r in rows])),
            "mean_content_updates": float(np.mean([sum(a in ACTIONS[:5] for a in r["actions"]) for r in rows])),
            "failures": sum(r["failure"] is not None for r in rows),
            "strategy": strategy, "prefix": list(prefix), "confirmation": False}


def inference_controls(model, directory, profile, *, seed, protocol):
    controls = {"encoder_only": ("stop", ()), "one_shared_update": ("stop", ("shared",)),
                "fixed_multi": ("fixed", ()), "dynamic_multi": ("dynamic", ())}
    return {name: evaluate(model, Path(directory)/name, profile, seed=seed, protocol=protocol,
                           strategy=strategy, prefix=prefix)
            for name, (strategy, prefix) in controls.items()}
