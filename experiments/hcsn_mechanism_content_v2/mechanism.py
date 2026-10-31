"""Controlled content-tracking assay, not a natural copy/AV benchmark.

READ reveals content and physical state after one tick, never resets the world.
STOP disables later sensing/control; all mandatory outputs and their costs remain.
The task-value controller is a receding, one-planned-read model heuristic, not an
optimal QVI oracle. Its simulated futures use shared estimates, never true paths.
"""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from .renewal import (GatedPropagator, LearnedCore, Physics, RenewalCore,
                      content_from_counts, fit_ordinary, shared_calibration)


@dataclass
class Observation:
    time: float
    x: float
    refractory_remaining: float
    content_probs: list
    has_read: bool


@dataclass(frozen=True)
class Config:
    dt: float = .15
    ticks: int = 20
    deadlines: tuple = (5, 10, 15, 20)
    budget: int = 3
    classes: int = 5
    read_cost: float = .04
    light_threshold: float = .28
    particles: int = 4
    condition: str = "matched"


def transition_matrix(k):
    matrix = np.zeros((k, k))
    for i in range(k):
        matrix[i, i] = .15
        matrix[(i + 1) % k, i] = .55
        matrix[(i - 1) % k, i] = .30
    return matrix


def generate_path(rng, physics, grid, x, content, transition, remaining=0.0):
    """Jointly consistent IG event times and 3-D Bessel-bridge observations.

    Conditional on a first hitting time, the radial Brownian bridge is the
    first-passage bridge; the constant drift cancels under that conditioning.
    All arm READ schedules index this same pre-generated joint trajectory.
    """
    if physics.nu >= 0:
        raise ValueError("independent simulator requires negative drift")
    if remaining > 0 and not np.isclose(x, physics.reset):
        raise ValueError("invalid refractory initial state")
    start = float(grid[0]) + remaining
    hit = start + rng.wald(x / -physics.nu, x*x / physics.sigma**2)
    vector, previous = np.array([x, 0., 0.]), start
    xs, rests, contents, events = [], [], [], []
    for now in grid:
        while now >= hit:
            old = content
            content = int(rng.choice(len(transition), p=transition[:, content]))
            events.append({"time": float(hit), "before": old, "after": content})
            start = hit + physics.refractory
            hit = start + rng.wald(physics.reset / -physics.nu,
                                   physics.reset**2 / physics.sigma**2)
            vector, previous = np.array([physics.reset, 0., 0.]), start
        if now < start:
            gap, rest = physics.reset, start - now
        else:
            delta = max(float(now - previous), 0.)
            ratio = (hit - now) / (hit - previous)
            vector = ratio * vector + physics.sigma * np.sqrt(delta * ratio) * rng.normal(size=3)
            previous = float(now)
            gap, rest = float(np.linalg.norm(vector)), 0.0
        xs.append(gap); rests.append(rest); contents.append(content)
    return {"x": xs, "refractory_remaining": rests, "content": contents, "events": events}


def predict(core, observation, now, physics, transition):
    before = time.perf_counter()
    counts = core.counts(observation.x, max(now - observation.time, 0), physics,
                         observation.refractory_remaining)
    probabilities = content_from_counts(counts, observation.content_probs, transition)
    core.evaluation_seconds = getattr(core, "evaluation_seconds", 0.) + time.perf_counter() - before
    return probabilities, {"event_probability": float(1 - counts[0]),
                            "expected_events": float(counts @ np.arange(len(counts))),
                            "count_probabilities": counts.tolist()}


def policy_prediction(core, obs, now, physics, matrix, suppress_events):
    if suppress_events and obs.has_read:
        return np.asarray(obs.content_probs)
    return predict(core, obs, now, physics, matrix)[0]


def choose_action(core, controller, obs, tick, budget, physics, matrix, config,
                  simulation_seed, suppress_events=False):
    """No actual world/path object is accepted by this policy interface."""
    future = [d for d in config.deadlines if d > tick]
    if not future or budget <= 0:
        return "STOP", {"reason": "no_future_output_or_budget", "simulations": 0}
    prior = {d: policy_prediction(core, obs, d * config.dt, physics, matrix,
                                  suppress_events) for d in future}
    if controller == "lightweight":
        error = float(1 - prior[future[0]].max())
        request = "READ" if error > config.light_threshold and future[0] - tick <= 2 else "WAIT"
        return request, {"forecast_error": error, "simulations": 0}
    # Shared estimated model, sampled without consulting the actual future.
    candidates = sorted(set([tick + 1] + future))
    start_tick = round(obs.time / config.dt)
    grid = np.arange(start_tick, config.ticks + 1) * config.dt
    rng = np.random.default_rng(simulation_seed)
    samples = [generate_path(rng, physics, grid, obs.x,
                            int(rng.choice(config.classes, p=obs.content_probs)), matrix,
                            obs.refractory_remaining) for _ in range(config.particles)]
    baseline = sum(1 - p.max() for p in prior.values()) / len(config.deadlines)
    values = []
    for arrival in candidates:
        loss = 0.
        for sample in samples:
            index = arrival - start_tick
            fake_obs = Observation(arrival * config.dt, sample["x"][index],
                                   sample["refractory_remaining"][index],
                                   np.eye(config.classes)[sample["content"][index]].tolist(), True)
            for deadline in future:
                predicted = (prior[deadline] if deadline < arrival else
                             policy_prediction(core, fake_obs, deadline * config.dt,
                                               physics, matrix, suppress_events))
                loss += 1 - predicted.max()
        loss /= config.particles * len(config.deadlines)
        values.append({"arrival_tick": arrival, "net_value": float(baseline - loss - config.read_cost)})
    best = max(values, key=lambda row: (row["net_value"], -row["arrival_tick"]))
    action = "STOP" if best["net_value"] <= 0 else ("READ" if best["arrival_tick"] == tick + 1 else "WAIT")
    return action, {"candidate_values": values, "selected_arrival": best["arrival_tick"],
                    "simulations": config.particles, "value_scope": "one_planned_read_heuristic"}


class FrozenContentCore:
    """Diagnostic hold-last-content readout, always replayed with fixed actions."""
    name = "frozen_content"
    calls = work = cdf_terms = 0

    def counts(self, x, horizon, physics, remaining=0):
        self.calls += 1
        return np.array([1.])


def run_arm(core, controller, episode, config, suppress_events=False, forced_actions=None):
    path, physics = episode["path"], Physics(**episode["calibration"]["estimated"])
    matrix = transition_matrix(config.classes)
    obs = Observation(0., episode["initial_x"], 0., [1 / config.classes] * config.classes, False)
    budget, pending, stopped, reads = config.budget, None, False, 0
    traces, access, predictions = [], [], []
    before = time.perf_counter(); controller_seconds = 0.
    core.evaluation_seconds = 0.
    core.calls = core.work = core.cdf_terms = 0
    for tick in range(config.ticks + 1):
        now = tick * config.dt
        if pending == tick:
            obs = Observation(now, path["x"][tick], path["refractory_remaining"][tick],
                              np.eye(config.classes)[path["content"][tick]].tolist(), True)
            access.append({"request_tick": tick - 1, "reveal_tick": tick,
                           "observed_state": asdict(obs), "external_state_reset": False})
            pending = None
        if tick in config.deadlines:
            probabilities, event = predict(core, obs, now, physics, matrix)
            truth = path["content"][tick]
            predictions.append({"tick": tick, "probabilities": probabilities.tolist(),
                                "truth_for_scoring_only": truth, "observed_state": asdict(obs),
                                "horizon_since_read": now - obs.time, **event,
                                "correct": int(probabilities.argmax() == truth),
                                "nll": float(-np.log(max(probabilities[truth], 1e-12))),
                                "brier": float(np.square(probabilities - np.eye(config.classes)[truth]).sum())})
        if tick == config.ticks or stopped:
            continue
        timing = time.perf_counter()
        if forced_actions is not None:
            requested, detail = forced_actions.get(tick, "STOP"), {"fixed_action_replay": True}
        else:
            simulation_seed = int(np.random.SeedSequence([episode["seed"], tick, 4337]).generate_state(1)[0])
            requested, detail = choose_action(core, controller, obs, tick, budget, physics,
                                               matrix, config, simulation_seed,
                                               suppress_events)
        controller_seconds += time.perf_counter() - timing
        executed, guard = requested, None
        if requested == "READ" and (budget <= 0 or pending is not None):
            executed, guard = "WAIT", "budget_or_inflight"
        if executed == "READ":
            budget -= 1; reads += 1; pending = tick + 1
        if executed == "STOP":
            stopped = True
        visible, _ = predict(core, obs, now, physics, matrix)
        traces.append({"tick": tick, "requested_action": requested, "executed_action": executed,
                       "guard": guard, "budget_after": budget, "observed_state": asdict(obs),
                       "propagated_content": visible.tolist(), "read_reveal_tick": pending,
                       "physical_estimates": asdict(physics), "policy_detail": detail,
                       "actual_future_available_to_policy": False})
    wall = time.perf_counter() - before
    summary = {"accuracy": float(np.mean([p["correct"] for p in predictions])),
               "nll": float(np.mean([p["nll"] for p in predictions])),
               "brier": float(np.mean([p["brier"] for p in predictions])), "reads": reads,
               "read_cost": reads * config.read_cost, "arm_wall_seconds": wall,
               "controller_wall_seconds_inclusive": controller_seconds,
               "core_wall_seconds_inclusive": core.evaluation_seconds,
               "core_calls": core.calls, "integration_evaluations": core.work,
               "cdf_terms": core.cdf_terms, "mandatory_outputs": len(predictions),
               "output_horizon": config.ticks * config.dt, "stop_disables_future_reads_only": True}
    summary["net_reward"] = summary["accuracy"] - summary["read_cost"]
    summary["task_utility_definition"] = "accuracy_minus_READ_fees_CPU_not_monetized"
    return summary, traces, access, predictions


def make_episode(seed, config):
    rng = np.random.default_rng(seed)
    nominal_refractory = rng.uniform(.16, .28)
    sampled_factor = rng.choice([.65, 1.45])
    factor = sampled_factor if config.condition == "hidden_refractory_mismatch" else 1.
    truth = Physics(-rng.uniform(.3, 1.0), rng.uniform(.2, .65),
                    rng.uniform(.4, 1.0), nominal_refractory * factor)
    calibration_start = time.perf_counter()
    estimates, record = shared_calibration(rng, truth)
    estimates = Physics(estimates.nu, estimates.sigma, estimates.reset, nominal_refractory)
    record["estimated"] = asdict(estimates)
    record["refractory_estimate_source"] = "public_nominal_not_hidden_true_duration"
    record["wall_seconds"] = time.perf_counter() - calibration_start
    x = rng.uniform(.3, 1.3)
    grid = np.arange(config.ticks + 1) * config.dt
    path = generate_path(rng, truth, grid, x, int(rng.integers(config.classes)),
                         transition_matrix(config.classes))
    return {"seed": seed, "initial_x": x, "calibration": record, "path": path,
            "condition": config.condition, "initial_content_hidden_until_READ": True}


def first_divergence(left, right):
    by_tick = {row["tick"]: row for row in right}
    for a in left:
        b = by_tick.get(a["tick"])
        if b is None or a["executed_action"] != b["executed_action"]:
            return {"tick": a["tick"], "kind": "action_or_stopping", "left": a, "right": b}
        if not np.allclose(a["propagated_content"], b["propagated_content"], atol=1e-8):
            return {"tick": a["tick"], "kind": "content", "left": a, "right": b}
    return None


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fit = sub.add_parser("fit")
    fit.add_argument("--output", required=True); fit.add_argument("--seed", type=int, default=1701)
    fit.add_argument("--train-size", type=int, default=8192); fit.add_argument("--epochs", type=int, default=80)
    fit.add_argument("--width", type=int, default=128); fit.add_argument("--cap", type=int, default=32)
    run = sub.add_parser("run")
    run.add_argument("--output", required=True); run.add_argument("--checkpoint", required=True)
    run.add_argument("--split", choices=["development", "test"], required=True)
    run.add_argument("--seed", type=int, default=4001); run.add_argument("--episodes", type=int, default=8)
    run.add_argument("--particles", type=int, default=4); run.add_argument("--read-cost", type=float, default=.04)
    run.add_argument("--light-threshold", type=float, default=.28)
    run.add_argument("--condition", choices=["matched", "hidden_refractory_mismatch"], default="matched")
    args = parser.parse_args(); torch.set_num_threads(1)
    output = Path(args.output); output.mkdir(parents=True, exist_ok=False)
    job = vars(args).copy(); job["schema"] = "hcsn_mechanism_content_v2.1"
    job["created_unix"] = time.time(); write_json(output / "job.json", job)
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    if args.command == "fit":
        ordinary, report, dataset = fit_ordinary(args.seed, args.train_size, args.epochs, args.width, args.cap)
        cpu_after = resource.getrusage(resource.RUSAGE_SELF)
        report["cpu_seconds"] = cpu_after.ru_utime + cpu_after.ru_stime - cpu_before.ru_utime - cpu_before.ru_stime
        np.savez_compressed(output / "training.npz", **dataset)
        torch.save({"state_dict": ordinary.model.state_dict(), "report": report}, output / "ordinary.pt")
        write_json(output / "training.json", report)
        print(json.dumps(report)); return
    checkpoint_path = Path(args.checkpoint)
    checkpoint = torch.load(checkpoint_path, weights_only=False, map_location="cpu")
    report = checkpoint["report"]
    model = GatedPropagator(report["width"], report["cap"])
    model.load_state_dict(checkpoint["state_dict"]); model.eval()
    config = Config(read_cost=args.read_cost, light_threshold=args.light_threshold,
                    particles=args.particles, condition=args.condition)
    checkpoint_sha = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    write_json(output / "selection.json", {"split": args.split, "checkpoint": str(checkpoint_path),
               "checkpoint_sha256": checkpoint_sha, "test_based_selection": False,
               "written_before_episode_generation": True, "config": asdict(config),
               "seed_namespace": "SeedSequence(requested_seed,index,split_code)",
               "controller": "one_planned_read_receding_heuristic_not_optimal_oracle"})
    warmup_start = time.perf_counter()
    for warm in (LearnedCore(model, report["cap"]), RenewalCore(cap=report["cap"])):
        warm.counts(.7, .8, Physics(-.6, .4, .6, .2))
    warmup_seconds = time.perf_counter() - warmup_start
    all_summary, traces, access, predictions, episodes, divergence = [], [], [], [], [], []
    for index in range(args.episodes):
        split_code = 311 if args.split == "development" else 929
        episode_seed = int(np.random.SeedSequence([args.seed, index, split_code]).generate_state(1)[0])
        episode = make_episode(episode_seed, config); episodes.append(episode)
        local_traces = {}
        arms = [(c, v) for c in ("ordinary_gated", "analytic") for v in ("lightweight", "task_value")]
        np.random.default_rng(episode_seed + 501).shuffle(arms)
        episode["predetermined_arm_order"] = [f"{c}__{v}" for c, v in arms]
        for core_name, controller in arms:
            core = LearnedCore(model, report["cap"]) if core_name == "ordinary_gated" else RenewalCore(cap=report["cap"])
            arm = f"{core_name}__{controller}"
            summary, trace, observed, predicted = run_arm(core, controller, episode, config)
            identity = {"episode": index, "seed": episode["seed"], "split": args.split,
                        "arm": arm, "core": core_name, "controller": controller}
            all_summary.append({**identity, **summary}); local_traces[arm] = trace
            traces.extend({**identity, **row} for row in trace)
            access.extend({**identity, **row} for row in observed)
            predictions.extend({**identity, **row} for row in predicted)
        suppressed = run_arm(RenewalCore(cap=report["cap"]), "task_value", episode, config, True)
        identity = {"episode": index, "seed": episode["seed"], "split": args.split,
                    "arm": "analytic__task_value__forecast_risk_suppressed", "core": "analytic",
                    "controller": "task_value", "diagnostic_only": True}
        all_summary.append({**identity, **suppressed[0]})
        traces.extend({**identity, **row} for row in suppressed[1])
        access.extend({**identity, **row} for row in suppressed[2])
        predictions.extend({**identity, **row} for row in suppressed[3])
        replay_traces = {}
        schedule = {r["tick"]: r["executed_action"] for r in local_traces["analytic__lightweight"]}
        for replay_core in (LearnedCore(model, report["cap"]), FrozenContentCore()):
            replay = run_arm(replay_core, "fixed_action_replay", episode, config, forced_actions=schedule)
            identity = {"episode": index, "seed": episode["seed"], "split": args.split,
                        "arm": f"{replay_core.name}__fixed_analytic_lightweight_actions",
                        "core": replay_core.name, "controller": "fixed_action_replay", "diagnostic_only": True}
            all_summary.append({**identity, **replay[0]}); replay_traces[replay_core.name] = replay[1]
            traces.extend({**identity, **row} for row in replay[1])
            access.extend({**identity, **row} for row in replay[2])
            predictions.extend({**identity, **row} for row in replay[3])
        divergence.append({"episode": index,
                           "core_switch": first_divergence(local_traces["ordinary_gated__task_value"], local_traces["analytic__task_value"]),
                           "fixed_action_core": first_divergence(local_traces["analytic__lightweight"], replay_traces["ordinary_gated"]),
                           "frozen_content": first_divergence(local_traces["analytic__lightweight"], replay_traces["frozen_content"]),
                           "risk_intervention": first_divergence(local_traces["analytic__task_value"], suppressed[1])})
    cpu_after = resource.getrusage(resource.RUSAGE_SELF)
    summary = {"scope": "controlled_renewal_content_assay_not_natural_AV_or_SSM_superiority",
               "capacity_and_prior": {"ordinary_trainable_parameters": report["parameters"],
                                      "analytic_trainable_core_parameters": 0,
                                      "analytic_known_renewal_law": True,
                                      "shared_physical_calibration_and_observation_packet": True},
               "forecast_risk_suppression_scope": "policy_forecasts_hold_last_observed_content_after_READ; output_core_unchanged; not_independent_Put_channel_ablation",
               "config": asdict(config), "episodes": all_summary, "training_cost_once": report,
               "calibration_wall_seconds": sum(e["calibration"]["wall_seconds"] for e in episodes),
               "warmup_wall_seconds": warmup_seconds,
               "run_cpu_seconds": cpu_after.ru_utime + cpu_after.ru_stime - cpu_before.ru_utime - cpu_before.ru_stime,
               "checkpoint_sha256": checkpoint_sha,
               "first_divergences": divergence, "timing_fields_inclusive_not_additive": True}
    write_json(output / "summary.json", summary)
    for name, rows in (("trace", traces), ("access", access), ("predictions", predictions), ("episodes", episodes)):
        write_jsonl(output / f"{name}.jsonl", rows)
    print(json.dumps({"output": str(output), "episodes": args.episodes,
                      "run_cpu_seconds": summary["run_cpu_seconds"]}))


if __name__ == "__main__":
    main()
